"""Exact TC archive graph checks through the production recovery CLI."""
import gzip
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import cache, cache_recovery, toolchain_archive

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cache_recovery.py'


class ToolchainArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'root'
        self.archive = self.base / 'archive'
        self.root.mkdir()
        self.archive.mkdir()

    def cli(self):
        return subprocess.run([sys.executable, str(SCRIPT), 'restore', 'toolchain',
                               str(self.root), str(self.archive), 'matched',
                               '--restored', 'matched', '--outcome', 'success'],
                              text=True, capture_output=True)

    def archive_entries(self, extra=(), roots=None):
        with tarfile.open(self.archive / 'toolchain.tar.gz', 'w:gz') as tf:
            for name in ('build_dir/host', 'staging_dir/host', *(roots if roots is not None else (
                    'build_dir/toolchain-test', 'staging_dir/toolchain-test'))):
                item = tarfile.TarInfo(name)
                item.type = tarfile.DIRTYPE
                tf.addfile(item)
            item = tarfile.TarInfo('staging_dir/host/bin/ccache')
            item.mode = 0o755
            item.size = 2
            tf.addfile(item, io.BytesIO(b'ok'))
            for item in extra:
                tf.addfile(item, io.BytesIO(b'x' * item.size) if item.isfile() else None)
        (self.archive / 'key').write_text('matched\n')

    def test_complete_root_sets_are_checked_before_extract_and_recover_cold(self):
        cases = (
            ('build_dir/toolchain-a', 'staging_dir/toolchain-b'),
            ('build_dir/toolchain-test', 'staging_dir/toolchain-test', 'build_dir/toolchain-extra'),
            ('build_dir/toolchain-test', 'staging_dir/toolchain-test', 'staging_dir/toolchain-extra'),
        )
        for roots in cases:
            with self.subTest(roots=roots):
                self.archive_entries(roots=roots)
                with patch.object(toolchain_archive.subprocess, 'run') as extract:
                    with self.assertRaisesRegex(ValueError, 'mismatched toolchain artifact roots'):
                        toolchain_archive.extract(self.archive / 'toolchain.tar.gz', self.root)
                    extract.assert_not_called()
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
                self.assertIn('mismatched toolchain artifact roots', result.stderr)
                self.assertEqual(list(self.root.iterdir()), [])
                self.assertEqual(list(self.archive.iterdir()), [])

    def test_implicit_extra_root_and_non_directory_root_are_rejected(self):
        cases = [self.member('build_dir/toolchain-extra/payload'),
                 self.member('build_dir/toolchain-extra'),
                 self.member('staging_dir/toolchain-extra', tarfile.SYMTYPE, 'toolchain-test')]
        for entry in cases:
            with self.subTest(name=entry.name, type=entry.type):
                self.archive_entries([entry])
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
                self.assertIn('incomplete toolchain artifact set', result.stderr)
                self.assertEqual(list(self.root.iterdir()), [])
                self.assertEqual(list(self.archive.iterdir()), [])

    def test_matching_multiple_generations_pack_and_restore(self):
        roots = tuple(f'{base}/toolchain-{generation}' for base in ('build_dir', 'staging_dir')
                      for generation in ('a', 'b'))
        self.archive_entries(roots=roots)
        self.assertEqual(self.cli().stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        cache.pack(self.root, self.archive, 'toolchain', 'matched')
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        self.assertTrue(all((self.root / name).is_dir() for name in roots))

    def test_pack_rejects_mismatched_extra_and_nondirectory_roots_before_tar(self):
        self.archive_entries()
        self.assertIn('hit=true\n', self.cli().stdout)
        base = self.root / 'staging_dir'
        for bad in ('mismatched', 'extra', 'file', 'symlink'):
            with self.subTest(bad=bad):
                path = base / 'toolchain-extra'
                if bad == 'mismatched':
                    (base / 'toolchain-test').rename(path)
                elif bad == 'extra':
                    path.mkdir()
                elif bad == 'file':
                    path.write_text('not a directory')
                else:
                    path.symlink_to('toolchain-test', target_is_directory=True)
                try:
                    with patch.object(cache.subprocess, 'run', wraps=subprocess.run) as tar:
                        with self.assertRaisesRegex(ValueError, 'toolchain artifact'):
                            cache.pack(self.root, self.archive, 'toolchain', 'matched')
                        tar.assert_not_called()
                    self.assertEqual(list(self.archive.iterdir()), [])
                finally:
                    if bad == 'mismatched':
                        path.rename(base / 'toolchain-test')
                    elif bad == 'extra':
                        path.rmdir()
                    else:
                        path.unlink()

    def test_recovery_rechecks_complete_restored_root_sets(self):
        # Keep the post-extract health boundary independent of header validation.
        self.archive_entries()
        def incomplete_restore(root, archive, expected):
            for name in ('build_dir/host', 'staging_dir/host',
                         'build_dir/toolchain-a', 'staging_dir/toolchain-b'):
                (root / name).mkdir(parents=True)
            binary = root / 'staging_dir/host/bin/ccache'
            binary.parent.mkdir()
            binary.write_bytes(b'not executed')
            binary.chmod(0o755)
        with patch.object(cache, 'restore', side_effect=incomplete_restore):
            import contextlib
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cache_recovery.restore('toolchain', self.root, self.archive, 'matched', 'matched', 'success')
        self.assertEqual(output.getvalue(), 'hit=false\nmatched-key=\npoisoned=true\n')
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(list(self.archive.iterdir()), [])

    def test_restore_reports_distinct_archive_phases(self):
        self.archive_entries()
        result = self.cli()
        self.assertEqual(result.stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n', result.stderr)
        self.assertRegex(result.stderr, r'Toolchain archive timing: format=gzip validate=\d+\.\d+s extract=\d+\.\d+s')

    def test_gzip_trailer_rejected_before_native_extraction(self):
        archive = self.archive / 'toolchain.tar.gz'
        for failure in ('checksum', 'truncated'):
            with self.subTest(failure=failure):
                self.archive_entries()
                data = archive.read_bytes()
                archive.write_bytes(data[:-8] + bytes([data[-8] ^ 1]) + data[-7:]
                                    if failure == 'checksum' else data[:-4])
                with patch.object(toolchain_archive.subprocess, 'run') as extract:
                    with self.assertRaises((gzip.BadGzipFile, EOFError)):
                        toolchain_archive.extract(archive, self.root)
                    extract.assert_not_called()
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
                self.assertEqual(list(self.root.iterdir()), [])
                self.assertEqual(list(self.archive.iterdir()), [])

    def test_zstd_pack_and_ambiguous_restore(self):
        self.archive_entries()
        self.assertIn('hit=true\n', self.cli().stdout)
        legacy = self.archive / 'toolchain.tar.gz'
        data = legacy.read_bytes()
        packed = subprocess.run([sys.executable, str(SCRIPT.with_name('cache.py')),
                                 'toolchain', str(self.root), str(self.archive), 'matched'],
                                text=True, capture_output=True)
        self.assertEqual(packed.returncode, 0, packed.stdout + packed.stderr)
        self.assertFalse(legacy.exists())
        restored = self.cli()
        self.assertIn('hit=true\n', restored.stdout)
        self.assertIn('format=zstd', restored.stderr)
        legacy.write_bytes(data)
        rejected = self.cli()
        self.assertIn('poisoned=true\n', rejected.stdout)
        self.assertIn('ambiguous or nonregular toolchain archive', rejected.stderr)
        self.assertFalse((self.root / 'build_dir').exists())
        self.assertEqual(list(self.archive.iterdir()), [])

    def test_source_member_is_rejected_before_extraction(self):
        (self.root / '.config').write_text('original')
        item = tarfile.TarInfo('.config')
        item.size = 6
        self.archive_entries([item])
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / '.config').read_text(), 'original')
        self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
        self.assertFalse((self.root / 'staging_dir').exists())
        self.assertEqual(list(self.archive.iterdir()), [])

    @staticmethod
    def member(name, kind=tarfile.REGTYPE, target='', mode=0o644):
        item = tarfile.TarInfo(name)
        item.type, item.linkname, item.mode = kind, target, mode
        item.size = 1 if kind == tarfile.REGTYPE else 0
        return item

    def test_rejects_unsafe_members_and_link_graphs(self):
        m = self.member
        cases = [[m(name)] for name in (
            'target/payload', 'package/payload', 'staging_dir/hostpkg/payload',
            'build_dir/target-test/payload', '../escape', '/absolute',
            'build_dir/host/../../.config', 'build_dir/host/./alias',
            'build_dir/host//alias', 'staging_dir/host/bin/ccache')]
        cases += [
            [m('build_dir/host/fifo', tarfile.FIFOTYPE)],
            [m('build_dir/host/device', tarfile.CHRTYPE)],
            [m('build_dir/host/privileged', mode=0o4755)],
            [m('build_dir/host/link', tarfile.SYMTYPE, '../../.config')],
            [m('build_dir/host/link', tarfile.SYMTYPE, '/etc/passwd')],
            [m('build_dir/host/link', tarfile.LNKTYPE, '.config')],
            [m('build_dir/host/link', tarfile.LNKTYPE, 'build_dir/host/missing')],
            [m('build_dir/host/a', tarfile.SYMTYPE, 'b'),
             m('build_dir/host/b', tarfile.SYMTYPE, 'a')],
            [m('build_dir/host/link', tarfile.SYMTYPE, '/usr/bin'),
             m('build_dir/host/link/payload')],
            [m('build_dir/host/alias', tarfile.SYMTYPE, 'real'),
             m('build_dir/host/next', tarfile.SYMTYPE, 'alias/../real')],
        ]
        (self.root / '.config').write_text('original')
        for entries in cases:
            with self.subTest(entries=[(e.name, e.linkname) for e in entries]):
                self.archive_entries(entries)
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
                self.assertEqual((self.root / '.config').read_text(), 'original')
                self.assertFalse((self.root / 'build_dir').exists())
                self.assertFalse((self.root / 'staging_dir').exists())
                self.assertEqual(list(self.archive.iterdir()), [])

    def test_native_prerequisite_internal_and_system_links(self):
        scripts = self.root / 'scripts'
        scripts.mkdir(mode=0o755)
        for name in ('xxdi.pl', 'noop.sh'):
            script = scripts / name
            script.write_text('#!/bin/sh\nexit 0\n')
            script.chmod(0o755)
        m = self.member
        self.archive_entries([
            m('staging_dir/host/bin/xxd', tarfile.SYMTYPE, str(scripts / 'xxdi.pl')),
            m('staging_dir/host/bin/ldconfig', tarfile.SYMTYPE, str(scripts / 'noop.sh')),
            m('staging_dir/host/bin/sh', tarfile.SYMTYPE, '/bin/sh'),
            m('build_dir/toolchain-test/data'),
            m('build_dir/toolchain-test/hard', tarfile.LNKTYPE, 'build_dir/toolchain-test/data'),
            m('staging_dir/toolchain-test/link', tarfile.SYMTYPE, '../../build_dir/toolchain-test/data'),
        ])
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        self.assertEqual((self.root / 'staging_dir/toolchain-test/link').read_bytes(), b'x')
        self.assertEqual((self.root / 'build_dir/toolchain-test/hard').stat().st_ino,
                         (self.root / 'build_dir/toolchain-test/data').stat().st_ino)

    def test_native_autoreconf_script_link_packs_and_restores(self):
        # include/autotools.mk in official v25.12.2 creates this absolute
        # source-script link inside host packages; do not dereference it.
        script = self.root / 'scripts/config.rpath'
        script.parent.mkdir(mode=0o755)
        script.write_text('#!/bin/sh\nexit 0\n')
        script.chmod(0o755)
        self.archive_entries()
        self.assertEqual(self.cli().stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        link = self.root / 'build_dir/host/gmp-6.3.0/config.rpath'
        link.parent.mkdir()
        subprocess.run(['ln', '-s', str(script), str(link)], check=True)
        pack = subprocess.run([sys.executable, str(SCRIPT.with_name('cache.py')),
                               'toolchain', str(self.root), str(self.archive), 'matched'],
                              text=True, capture_output=True)
        self.assertEqual(pack.returncode, 0, pack.stdout + pack.stderr)
        raw = subprocess.check_output(['zstd', '-dc', '--', str(self.archive / 'toolchain.tar.zst')])
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as tf:
            member = tf.getmember(link.relative_to(self.root).as_posix())
            self.assertTrue(member.issym())
            self.assertEqual(member.linkname, str(script))
        restored = self.cli()
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(restored.stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.read_bytes(), script.read_bytes())

    def test_autoreconf_exception_remains_exact_and_source_locked(self):
        script = self.root / 'scripts/config.rpath'
        script.parent.mkdir(mode=0o755)
        good = ('build_dir/host/gmp-6.3.0/config.rpath', str(script), 'regular')
        cases = [
            ('build_dir/host/gmp-6.3.0/config.rpath', str(self.root / 'scripts/noop.sh'), 'regular'),
            ('build_dir/host/gmp-6.3.0/other', str(script), 'regular'),
            ('staging_dir/host/share/config.rpath', str(script), 'regular'),
            ('build_dir/host/config.rpath', str(script), 'regular'),
            (good[0], '../../../scripts/config.rpath', 'regular'),
            (good[0], str(script), 'missing'),
            (good[0], str(script), 'nonexec'),
            (good[0], str(script), 'writable'),
            (good[0], str(script), 'symlink'),
        ]
        for name, target, state in cases:
            with self.subTest(name=name, target=target, state=state):
                script.unlink(missing_ok=True)
                if state != 'missing':
                    script.write_text('#!/bin/sh\nexit 0\n')
                    script.chmod({'nonexec': 0o644, 'writable': 0o777}.get(state, 0o755))
                if state == 'symlink':
                    script.unlink()
                    script.symlink_to('/bin/sh')
                self.archive_entries([self.member(name, tarfile.SYMTYPE, target)])
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
                self.assertFalse((self.root / 'build_dir').exists())
                self.assertEqual(list(self.archive.iterdir()), [])

    def test_valid_toolchain_graph_restores_and_hits(self):
        self.archive_entries()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        self.assertEqual((self.root / 'staging_dir/host/bin/ccache').read_bytes(), b'ok')
