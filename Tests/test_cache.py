import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cache', Path(__file__).resolve().parents[1] / 'Scripts/Cache.py')
assert spec is not None and spec.loader is not None
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)
REF = 'refs/heads/main'
KEY = cache.scope(REF) + 'tc-new'


def row(n, key=KEY, ref=REF, size=100, created='2026-01-02'):
    return dict(id=n, key=key, ref=ref, size_in_bytes=size, created_at=created)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'tree'
        self.root.mkdir()

    def source(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in ['tools/flock/src/f.c', 'toolchain/Makefile', 'include/host-build.mk',
                     'target/linux/qualcommax/Makefile', 'scripts/config/Makefile', '.config']:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('input\n')
        (self.root / '.gitignore').write_text('*.o\nconf\n')

    def prepare(self):
        with patch.object(cache, 'run', wraps=cache.run) as run:
            return cache.prepare(self.root, REF, 'fixed-host')['tc-key']

    def trees(self):
        for name in ['build_dir/host/flock/.built', 'staging_dir/host/bin/flock',
                     'build_dir/toolchain-test/.built', 'staging_dir/toolchain-test/bin/gcc',
                     'dl/src.tar', '.ccache/object']:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'cache data' * 100)
            os.utime(p, ns=(1700000000123456789, 1700000000123456789))

    def test_key_mtime_stability_and_input_changes(self):
        self.source()
        self.trees()
        stamp = self.root / 'build_dir/host/flock/.built'
        old = stamp.stat().st_mtime_ns
        a = self.prepare()
        os.utime(self.root / 'tools/flock/src/f.c', None)
        self.assertEqual(a, self.prepare())
        self.assertEqual(old, stamp.stat().st_mtime_ns)
        (self.root / 'scripts/config/conf').write_text('generated executable')
        self.assertEqual(a, self.prepare())
        for name in ['tools/flock/src/f.c', '.config', 'target/linux/qualcommax/Makefile']:
            p = self.root / name
            original = p.read_text()
            p.write_text('changed')
            self.assertNotEqual(a, self.prepare())
            p.write_text(original)
        p = self.root / 'tools/flock/src/f.c'
        p.chmod(0o755)
        self.assertNotEqual(a, self.prepare())

    def test_links_fail_closed(self):
        self.source()
        (self.root / 'tools/external').symlink_to('/etc/hostname')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_archive_pax_pair_roundtrip(self):
        self.trees()
        (self.root / 'staging_dir/host/bin/cc').symlink_to('/usr/bin/gcc')
        for tier, roots in [('tc', ['build_dir', 'staging_dir']), ('rolling', ['dl', '.ccache'])]:
            archive = self.base / (tier + '.tar.gz')
            with patch.object(cache.subprocess, 'run', wraps=subprocess.run) as run:
                result = cache.pack(self.root, tier, archive)
                self.assertEqual(1, run.call_count)
            self.assertEqual(archive.stat().st_size, result['bytes'])
            for root in roots:
                shutil.rmtree(self.root / root)
            cache.unpack(self.root, tier, archive)
        self.assertEqual(1700000000123456789,
                         (self.root / 'build_dir/host/flock/.built').stat().st_mtime_ns)
        self.assertEqual('/usr/bin/gcc', os.readlink(self.root / 'staging_dir/host/bin/cc'))
        stale = self.root / 'staging_dir/host/stale'
        stale.write_text('defconfig output')
        untouched = self.root / 'staging_dir/hostpkg/keep'
        untouched.parent.mkdir()
        untouched.write_text('keep')
        cache.unpack(self.root, 'tc', self.base / 'tc.tar.gz')
        self.assertFalse(stale.exists())
        self.assertEqual('keep', untouched.read_text())
        self.assertFalse(list(self.root.glob('.cache-backup-*')))

    def test_pack_prefers_pigz_with_gzip_fallback(self):
        self.trees()
        for executable, expected in [('/usr/bin/pigz', 'pigz -1'), (None, 'gzip -1')]:
            with patch.object(cache.shutil, 'which', return_value=executable), patch.object(cache.subprocess, 'run') as run:
                archive = self.base / 'compress.gz'
                archive.with_name('compress.gz.partial').write_bytes(b'archive')
                cache.pack(self.root, 'tc', archive)
                self.assertEqual(expected, run.call_args.args[0][3])

    def test_schema_changes_invalidate_key(self):
        self.source()
        a = self.prepare()
        with patch.object(cache, 'SCHEMA', cache.SCHEMA + '-rule-change'):
            self.assertNotEqual(a, self.prepare())

    def test_restore_failure_rolls_back_existing_trees(self):
        self.trees()
        for tier in ['tc', 'rolling']:
            archive = self.base / (tier + '.gz')
            cache.pack(self.root, tier, archive)
            names = cache.paths(self.root, tier)
            for name in names:
                (self.root / name / 'old').write_text('original')
            protected = self.root / 'staging_dir/target-test/keep'
            protected.parent.mkdir(parents=True, exist_ok=True)
            protected.write_text('untouched')
            real_run = subprocess.run
            def failed_extract(*args, **kwargs):
                real_run(*args, **kwargs)
                raise subprocess.CalledProcessError(2, args[0])
            with patch.object(cache.subprocess, 'run', side_effect=failed_extract):
                with self.assertRaises(subprocess.CalledProcessError):
                    cache.unpack(self.root, tier, archive)
            for name in names:
                self.assertEqual('original', (self.root / name / 'old').read_text())
            self.assertEqual('untouched', protected.read_text())
            self.assertFalse(list(self.root.glob('.cache-backup-*')))

    @unittest.skipUnless(os.environ.get('CACHE_OPENWRT_ROOT'), 'set CACHE_OPENWRT_ROOT for real upstream flock build')
    def test_real_flock_cold_warm_existing_host_restore(self):
        # Isolate builds from the supplied checkout. Toolchain roots are fixtures;
        # flock itself uses the upstream Makefiles, stamp logic and C compiler.
        shutil.copytree(os.environ['CACHE_OPENWRT_ROOT'], self.root, dirs_exist_ok=True,
                        symlinks=True)
        def make(target):
            result = subprocess.run(['make', '-j1', target, 'V=s'], cwd=self.root,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(0, result.returncode, result.stdout)
            return result.stdout
        make('tools/flock/clean')
        make('defconfig')
        key = self.prepare()
        cold = make('tools/flock/compile')
        binary = self.root / 'staging_dir/host/bin/flock'
        self.assertTrue(binary.is_file(), cold)
        data, timestamp = binary.read_bytes(), binary.stat().st_mtime_ns
        for base in ['build_dir', 'staging_dir']:
            (self.root / base / 'toolchain-fixture').mkdir(exist_ok=True)
        archive = self.base / 'real-flock.gz'
        cache.pack(self.root, 'tc', archive)
        # Simulate final defconfig having already made host dirs and tools.
        (self.root / 'staging_dir/host/defconfig-marker').write_text('stale')
        binary.write_bytes(b'broken existing binary')
        cache.unpack(self.root, 'tc', archive)
        self.assertEqual(data, binary.read_bytes())
        self.assertEqual(timestamp, binary.stat().st_mtime_ns)
        self.assertFalse((self.root / 'staging_dir/host/defconfig-marker').exists())
        self.assertEqual(key, self.prepare())
        warm = make('tools/flock/compile')
        self.assertEqual(timestamp, binary.stat().st_mtime_ns, warm)
        self.assertEqual(data, binary.read_bytes())
        subprocess.run([str(binary), str(self.base / 'lock'), 'true'], check=True)
        source = self.root / 'tools/flock/src/flock.c'
        source.write_text(source.read_text() + '\n/* cache invalidation probe */\n')
        self.assertNotEqual(key, self.prepare())

    def test_no_partial_or_hostpkg(self):
        self.trees()
        shutil.rmtree(self.root / 'staging_dir/toolchain-test')
        with self.assertRaises(ValueError):
            cache.pack(self.root, 'tc', self.base / 'a.gz')
        self.assertFalse(cache.allowed('staging_dir/hostpkg/file', 'tc'))
        self.assertFalse(cache.allowed('../dl/file', 'rolling'))

    def test_malicious_archive(self):
        archive = self.base / 'bad.gz'
        with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT) as t:
            a = tarfile.TarInfo('dl/link')
            a.type = tarfile.SYMTYPE
            a.linkname = '/tmp'
            t.addfile(a)
            b = tarfile.TarInfo('dl/link/escape')
            b.size = 1
            t.addfile(b, io.BytesIO(b'x'))
        with self.assertRaises(ValueError):
            cache.unpack(self.root, 'rolling', archive)
        self.assertFalse((self.root / 'dl').exists())

    def test_budget_counts_other_namespaces_refs_and_overlap(self):
        rows = [row(1, key='legacy', size=9_950_000_000, ref='refs/heads/other')]
        self.assertFalse(cache.admission(rows, 10_000, KEY, REF)['admitted'])
        self.assertTrue(cache.admission([], 1_000_000_000, KEY, REF)['admitted'])
        self.assertFalse(cache.admission([row(1)], 100, KEY, REF)['admitted'])
        with self.assertRaises(ValueError):
            cache.admission([], 100, 'legacy-key', REF)

    def test_prune_scope_confirmation_readback(self):
        old = row(2, key=cache.scope(REF) + 'tc-old', created='2026-01-01')
        other = [row(3, key='old-cache'), row(4, ref='refs/heads/test'),
                 row(5, key=cache.scope(REF) + 'rolling-old'),
                 row(6, key=cache.scope(REF) + 'tc-newer', created='2026-01-03')]
        rows = [row(1), old] + other
        with patch.object(cache, 'inventory', side_effect=[rows, [row(1)] + other]), patch.object(cache.subprocess, 'run') as delete:
            self.assertEqual([2], cache.prune('owner/repo', REF, KEY, True)['deleted'])
            self.assertEqual(1, delete.call_count)
        for bad in [[], [row(1, size=0)], [row(1, ref='refs/heads/test')]]:
            with patch.object(cache, 'inventory', return_value=bad), patch.object(cache.subprocess, 'run') as delete:
                with self.assertRaises(ValueError):
                    cache.prune('owner/repo', REF, KEY, True)
                delete.assert_not_called()
        with patch.object(cache, 'inventory', side_effect=[rows, rows]), patch.object(cache.subprocess, 'run'):
            with self.assertRaises(ValueError):
                cache.prune('owner/repo', REF, KEY, True)

    def test_inventory_pagination_and_errors(self):
        import json
        with patch.object(cache, 'run', return_value=json.dumps([{'actions_caches': [row(1)]}, {'actions_caches': [row(2)]}]).encode()):
            self.assertEqual(2, len(cache.inventory('owner/repo')))
        with patch.object(cache, 'run', side_effect=subprocess.CalledProcessError(1, 'gh')):
            with self.assertRaises(subprocess.CalledProcessError):
                cache.prune('owner/repo', REF, KEY, True)


if __name__ == '__main__':
    unittest.main()
