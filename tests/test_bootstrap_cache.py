"""Bootstrap cache tests: native tar and simulated artifacts, never compilation."""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import tarfile
import io
import shutil

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/bootstrap_cache.py'


def assert_prepared_contract(test, module, root):
    # Explicit expectation, never infer acceptance from the implementation.
    expected = os.environ.get('BOOTSTRAP_EXPECT_CONTRACT', 'reviewed-independent')
    test.assertIn(expected, ('reviewed-independent', 'full-toolchain-bound'))
    digest = module.inventory(root)
    a = module.key(root, 'builder', 'tc-one')
    b = module.key(root, 'builder', 'tc-two')
    test.assertRegex(a, r'^[0-9a-f]{64}$')
    test.assertRegex(b, r'^[0-9a-f]{64}$')
    if expected == 'reviewed-independent':
        test.assertIn(digest, module.REVIEWED)
        test.assertEqual(a, b)
    else:
        test.assertNotIn(digest, module.REVIEWED)
        test.assertNotEqual(a, b)
    return expected


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        self.cache = Path(self.tmp.name) / 'cache'
        self.root.mkdir()
        (self.root / '.config').write_text('# Generated\n\nCONFIG_CCACHE=y\n')
        for name in ('tools', 'scripts'):
            (self.root / name).mkdir()
            (self.root / name / 'Makefile').write_text('# fixture\n')

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True)

    def module(self):
        spec = importlib.util.spec_from_file_location('bootstrap_cache', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_mx_reviewed_lock_is_post_custom_not_bare_sibling_source(self):
        m = self.module()
        self.assertEqual(m.REVIEWED, {
            '5e09e8d00cbee466260d9391bab5d5f38a41ed7a439e553a9ee49a517deb435f',
            'a6008400054b94165035f5a07888725ef3505818f63f5ad07db380214de04f4e'})

    @unittest.skipUnless(os.environ.get('MX_PREPARED_SOURCE'),
                         'set MX_PREPARED_SOURCE to exact post-custom MX source')
    def test_actual_mx_post_custom_matches_expected_contract(self):
        m = self.module()
        root = Path(os.environ['MX_PREPARED_SOURCE'])
        assert_prepared_contract(self, m, root)

    def test_prepared_expectation_never_infers_or_relaxes_review(self):
        m = self.module()
        digest = m.inventory(self.root)
        with patch.dict(os.environ, {'BOOTSTRAP_EXPECT_CONTRACT': 'full-toolchain-bound'}):
            assert_prepared_contract(self, m, self.root)
        # Default remains the strict historical reviewed-independent contract.
        with patch.dict(os.environ):
            os.environ.pop('BOOTSTRAP_EXPECT_CONTRACT', None)
            with self.assertRaises(AssertionError):
                assert_prepared_contract(self, m, self.root)
            setattr(m, 'REVIEWED', {digest})
            assert_prepared_contract(self, m, self.root)
        with patch.dict(os.environ, {'BOOTSTRAP_EXPECT_CONTRACT': 'full-toolchain-bound'}):
            with self.assertRaises(AssertionError):
                assert_prepared_contract(self, m, self.root)
        with patch.dict(os.environ, {'BOOTSTRAP_EXPECT_CONTRACT': 'auto'}):
            with self.assertRaises(AssertionError):
                assert_prepared_contract(self, m, self.root)

    def test_reviewed_inventory_has_independent_key(self):
        m = self.module()
        # A tiny reviewed contract exercises selection, not the production locks.
        for name in m.FIXED_INPUTS:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# audited input\n')
        digest = m.inventory(self.root)
        m.REVIEWED = {digest}
        a = m.key(self.root, 'builder', 'tc-one')
        self.assertEqual(a, m.key(self.root, 'builder', 'tc-two'))
        p = self.root / 'tools/Makefile'
        p.write_text('# changed\n')
        self.assertNotEqual(a, m.key(self.root, 'builder', 'tc-one'))
        self.assertNotEqual(m.key(self.root, 'builder', 'tc-one'),
                            m.key(self.root, 'builder', 'tc-two'))

    def test_external_make_fragment_content_mode_and_type_are_locked(self):
        m = self.module()
        fragment = self.root / '.external-packages.mk'
        fragment.write_text('EXTERNAL_PACKAGES:=reviewed\n')
        fragment.chmod(0o644)
        setattr(m, 'REVIEWED', {m.inventory(self.root)})
        baseline = m.key(self.root, 'builder', 'tc-one')
        self.assertEqual(baseline, m.key(self.root, 'builder', 'tc-two'))
        fragment.write_text('include /unreviewed/producer.mk\n')
        self.assertNotEqual(m.key(self.root, 'builder', 'tc-one'),
                            m.key(self.root, 'builder', 'tc-two'))
        fragment.write_text('EXTERNAL_PACKAGES:=reviewed\n')
        self.assertEqual(baseline, m.key(self.root, 'builder', 'tc-one'))
        fragment.chmod(0o600)
        self.assertNotEqual(baseline, m.key(self.root, 'builder', 'tc-one'))
        fragment.unlink()
        self.assertNotEqual(m.key(self.root, 'builder', 'tc-one'),
                            m.key(self.root, 'builder', 'tc-two'))
        fragment.mkdir()
        with self.assertRaises(ValueError):
            m.key(self.root, 'builder', 'tc-one')
        fragment.rmdir()
        fragment.symlink_to(self.root / 'tools/Makefile')
        with self.assertRaises(ValueError):
            m.key(self.root, 'builder', 'tc-one')

    def artifacts(self):
        for tool in ('ccache', 'cmake'):
            p = self.root / 'build_dir/host' / (tool + '-1.0')
            p.mkdir(parents=True)
            (p / '.built').write_text('')
            stamp = self.root / 'staging_dir/host/stamp' / ('.' + tool + '_installed')
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text('')
        ccache = self.root / 'staging_dir/host/bin/ccache'
        ccache.parent.mkdir()
        ccache.write_text('#!/bin/sh\nprintf "ccache simulated\\n"\n')
        ccache.chmod(0o755)
        ns = 1700000000123456789
        os.utime(self.root / 'build_dir/host/ccache-1.0/.built', ns=(ns, ns))
        return ns

    def test_native_archive_cli_rechecks_health_without_running_restored_binary(self):
        ns = self.artifacts()
        binary = self.root / 'staging_dir/host/bin/ccache'
        # This must never be executed by the archive structural health gate.
        binary.write_text('#!/bin/sh\nexit 99\n')
        binary.chmod(0o755)
        self.prereq_scripts()
        result = self.cli('pack', self.root, self.cache, 'tb-one')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli('restore', self.root, self.cache, 'tb-one')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('exact bootstrap restored', result.stdout)
        self.assertEqual((self.root / 'build_dir/host/ccache-1.0/.built').stat().st_mtime_ns, ns)
        self.assertTrue((self.root / 'staging_dir/host/bin/xxd').is_symlink())
        # Native tar with valid headers/stamps but an empty executable is cold.
        binary.write_bytes(b'')
        with tarfile.open(self.cache / 'bootstrap.tar.gz', 'w:gz',
                          format=tarfile.PAX_FORMAT) as archive:
            for name in self.module().ROOTS:
                archive.add(self.root / name, arcname=name)
        result = self.cli('restore', self.root, self.cache, 'tb-one')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('nonempty executable host ccache', result.stderr)
        self.assertFalse((self.root / 'build_dir/host').exists())
        self.assertFalse((self.root / 'staging_dir/host').exists())

    def test_pack_restore_pair_preserves_nanoseconds_and_toolchain(self):
        m = self.module()
        ns = self.artifacts()
        m.pack(self.root, self.cache, 'tb-one')
        self.assertTrue((self.cache / 'bootstrap.tar.gz').is_file())
        sentinel = self.root / 'staging_dir/toolchain-test/keep'
        sentinel.parent.mkdir()
        sentinel.write_text('toolchain')
        stale = self.root / 'build_dir/host/stale'
        stale.write_text('remove me')
        m.restore(self.root, self.cache, 'tb-one')
        self.assertFalse(stale.exists())
        self.assertEqual(sentinel.read_text(), 'toolchain')
        self.assertEqual((self.root / 'build_dir/host/ccache-1.0/.built').stat().st_mtime_ns, ns)
        exe = self.root / 'staging_dir/host/bin/ccache'
        self.assertEqual(subprocess.check_output([str(exe)], text=True), 'ccache simulated\n')

    def test_external_download_folder_fails_closed(self):
        m = self.module()
        (self.root / '.config').write_text('CONFIG_DOWNLOAD_FOLDER="/mutable/downloads"\n')
        with self.assertRaises(ValueError):
            m.key(self.root, 'builder', 'tc')

    def test_hostname_is_not_builder_identity(self):
        m = self.module()
        old = os.uname()
        with patch.object(m.os, 'uname', return_value=os.uname_result((old.sysname, 'ephemeral-one', old.release, old.version, old.machine))):
            a = m.key(self.root, 'builder', 'tc')
        with patch.object(m.os, 'uname', return_value=os.uname_result((old.sysname, 'ephemeral-two', old.release, old.version, old.machine))):
            self.assertEqual(a, m.key(self.root, 'builder', 'tc'))

    def test_builder_prereq_symlinks_survive_without_dereference(self):
        m = self.module()
        self.artifacts()
        compiler = Path(shutil.which('gcc') or '/usr/bin/python3')
        (self.root / 'staging_dir/host/bin/gcc').symlink_to(compiler)
        m.pack(self.root, self.cache, 'tb-one')
        m.restore(self.root, self.cache, 'tb-one')
        self.assertTrue((self.root / 'staging_dir/host/bin/gcc').is_symlink())
        self.assertEqual((self.root / 'staging_dir/host/bin/gcc').readlink(), compiler)

    def prereq_scripts(self):
        for tool, script in (('xxd', 'xxdi.pl'), ('ldconfig', 'noop.sh')):
            target = self.root / 'scripts' / script
            target.write_text('#!/bin/sh\nexit 0\n')
            target.chmod(0o755)
            (self.root / 'staging_dir/host/bin' / tool).symlink_to(target)

    def test_official_prereq_script_links_pack_restore_without_dereference(self):
        m = self.module()
        ns = self.artifacts()
        self.prereq_scripts()
        expected = m.key(self.root, 'builder', 'tc')
        m.pack(self.root, self.cache, expected)
        with tarfile.open(self.cache / 'bootstrap.tar.gz', 'r:gz') as tf:
            for tool in ('xxd', 'ldconfig'):
                self.assertTrue(tf.getmember('staging_dir/host/bin/' + tool).issym())
            self.assertFalse(any(item.name.startswith('scripts/') for item in tf))
        m.restore(self.root, self.cache, expected)
        for tool, script in (('xxd', 'xxdi.pl'), ('ldconfig', 'noop.sh')):
            link = self.root / 'staging_dir/host/bin' / tool
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.readlink(), self.root / 'scripts' / script)
        self.assertEqual((self.root / 'build_dir/host/ccache-1.0/.built').stat().st_mtime_ns, ns)

    def test_prereq_script_writable_ancestor_is_rejected(self):
        m = self.module()
        self.artifacts()
        self.prereq_scripts()
        m.pack(self.root, self.cache, 'tb-one')
        (self.root / 'scripts').chmod(0o777)
        with self.assertRaises(ValueError):
            m.restore(self.root, self.cache, 'tb-one')

    def test_prereq_script_exception_is_exact_location_and_target_only(self):
        m = self.module()
        self.artifacts()
        self.prereq_scripts()
        (self.root / 'scripts/other.sh').write_text('#!/bin/sh\nexit 0\n')
        (self.root / 'scripts/other.sh').chmod(0o755)
        self.cache.mkdir()
        archive = self.cache / 'bootstrap.tar.gz'
        for name, target, kind in (
                ('staging_dir/host/bin/xxd', 'scripts/noop.sh', tarfile.SYMTYPE),
                ('staging_dir/host/bin/ldconfig', 'scripts/xxdi.pl', tarfile.SYMTYPE),
                ('staging_dir/host/bin/xxd', 'scripts/other.sh', tarfile.SYMTYPE),
                ('staging_dir/host/bin/other', 'scripts/xxdi.pl', tarfile.SYMTYPE),
                ('build_dir/host/xxd', 'scripts/xxdi.pl', tarfile.SYMTYPE),
                ('staging_dir/host/xxd', 'scripts/xxdi.pl', tarfile.SYMTYPE),
                ('staging_dir/host/bin/xxd', 'scripts/../scripts/xxdi.pl', tarfile.SYMTYPE),
                ('staging_dir/host/bin/xxd', '../../../scripts/xxdi.pl', tarfile.SYMTYPE),
                ('staging_dir/host/bin/xxd', 'scripts/xxdi.pl', tarfile.LNKTYPE)):
            with self.subTest(name=name, target=target, kind=kind):
                with tarfile.open(archive, 'w:gz') as tf:
                    for root in m.ROOTS:
                        item = tarfile.TarInfo(root)
                        item.type = tarfile.DIRTYPE
                        tf.addfile(item)
                    item = tarfile.TarInfo(name)
                    item.type = kind
                    item.linkname = (target if target.startswith('../')
                                     else str(self.root / target))
                    tf.addfile(item)
                with self.assertRaises(ValueError):
                    m.validate_archive(archive, self.root)

    def test_prereq_script_target_safety_is_checked_before_restore_cleanup(self):
        m = self.module()
        self.artifacts()
        self.prereq_scripts()
        m.pack(self.root, self.cache, 'tb-one')
        sentinel = self.root / 'build_dir/host/keep-until-validated'
        sentinel.write_text('keep')
        target = self.root / 'scripts/xxdi.pl'
        for mode in (0o644, 0o777, 0o4755, 0o2755, 0o1755):
            with self.subTest(mode=oct(mode)):
                target.chmod(mode)
                with self.assertRaises(ValueError):
                    m.restore(self.root, self.cache, 'tb-one')
                self.assertTrue(sentinel.exists())
        target.chmod(0o755)
        target.unlink()
        with self.assertRaises(ValueError):
            m.restore(self.root, self.cache, 'tb-one')
        target.mkdir()
        with self.assertRaises(ValueError):
            m.restore(self.root, self.cache, 'tb-one')
        target.rmdir()
        target.symlink_to(self.root / 'scripts/noop.sh')
        with self.assertRaises(ValueError):
            m.restore(self.root, self.cache, 'tb-one')
        target.unlink()
        target.write_text('#!/bin/sh\nexit 0\n')
        target.chmod(0o755)
        scripts = self.root / 'scripts'
        moved = self.root / 'moved-scripts'
        scripts.rename(moved)
        scripts.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            m.restore(self.root, self.cache, 'tb-one')
        self.assertTrue(sentinel.exists())

    def test_prereq_script_content_and_mode_are_key_inputs(self):
        m = self.module()
        self.artifacts()
        self.prereq_scripts()
        setattr(m, 'REVIEWED', {m.inventory(self.root)})
        a = m.key(self.root, 'builder', 'tc-one')
        self.assertEqual(a, m.key(self.root, 'builder', 'tc-two'))
        target = self.root / 'scripts/xxdi.pl'
        target.write_text('#!/bin/sh\nexit 1\n')
        self.assertNotEqual(a, m.key(self.root, 'builder', 'tc-one'))
        target.write_text('#!/bin/sh\nexit 0\n')
        self.assertEqual(a, m.key(self.root, 'builder', 'tc-one'))
        target.chmod(0o744)
        self.assertNotEqual(a, m.key(self.root, 'builder', 'tc-one'))

    def test_absolute_internal_link_is_safe(self):
        m = self.module()
        self.artifacts()
        target = self.root / 'build_dir/host/ccache-1.0/.built'
        (self.root / 'build_dir/host/stamp-link').symlink_to(target)
        m.pack(self.root, self.cache, 'tb-one')
        m.restore(self.root, self.cache, 'tb-one')
        self.assertEqual((self.root / 'build_dir/host/stamp-link').readlink(), target)

    def test_cold_restore_cleans_only_host_roots(self):
        m = self.module()
        self.artifacts()
        sentinel = self.root / 'build_dir/toolchain-test/keep'
        sentinel.parent.mkdir()
        sentinel.write_text('keep')
        m.restore(self.root, self.cache, 'tb-one')
        self.assertEqual(sentinel.read_text(), 'keep')
        self.assertFalse((self.root / 'build_dir/host').exists())
        self.assertFalse((self.root / 'staging_dir/host').exists())

    def test_key_mismatch_rejects_before_deleting_host(self):
        m = self.module()
        self.artifacts()
        m.pack(self.root, self.cache, 'tb-one')
        with self.assertRaisesRegex(ValueError, 'key mismatch'):
            m.restore(self.root, self.cache, 'tb-two')
        self.assertTrue((self.root / 'staging_dir/host/bin/ccache').exists())

    def test_budget_declines_without_archive_or_key(self):
        m = self.module()
        self.artifacts()
        m.LIMIT = 1
        m.pack(self.root, self.cache, 'tb-one')
        self.assertFalse((self.cache / 'bootstrap.tar.gz').exists())
        self.assertFalse((self.cache / 'key').exists())

    def test_incomplete_pair_or_nonexecutable_ccache_cannot_seed(self):
        m = self.module()
        self.artifacts()
        binary = self.root / 'staging_dir/host/bin/ccache'
        binary.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'executable'):
            m.pack(self.root, self.cache, 'tb-one')
        binary.chmod(0o755)
        (self.root / 'staging_dir/host/stamp/.cmake_installed').unlink()
        with self.assertRaisesRegex(ValueError, 'completion stamps'):
            m.pack(self.root, self.cache, 'tb-one')
        self.assertFalse((self.cache / 'bootstrap.tar.gz').exists())

    def test_empty_executable_ccache_cannot_seed(self):
        m = self.module()
        self.artifacts()
        binary = self.root / 'staging_dir/host/bin/ccache'
        binary.write_bytes(b'')
        self.assertTrue(os.access(binary, os.X_OK))
        with self.assertRaisesRegex(ValueError, 'ccache'):
            m.pack(self.root, self.cache, 'tb-one')
        self.assertFalse((self.cache / 'bootstrap.tar.gz').exists())
        self.assertFalse((self.cache / 'key').exists())

    def test_archive_rejects_traversal_target_and_special_entries(self):
        m = self.module()
        self.cache.mkdir()
        for name, kind, target in (
                ('../escape', tarfile.REGTYPE, ''),
                ('/absolute', tarfile.REGTYPE, ''),
                ('build_dir/host/../../escape', tarfile.REGTYPE, ''),
                ('build_dir/toolchain-test/escape', tarfile.REGTYPE, ''),
                ('staging_dir/hostpkg/escape', tarfile.REGTYPE, ''),
                ('staging_dir/host/escape', tarfile.SYMTYPE, '/etc/passwd'),
                ('staging_dir/host/escape', tarfile.SYMTYPE, '../../../escape'),
                ('staging_dir/host/escape', tarfile.LNKTYPE, '/etc/passwd'),
                ('staging_dir/host/fifo', tarfile.FIFOTYPE, '')):
            with self.subTest(name=name, kind=kind, target=target):
                archive = self.cache / 'bootstrap.tar.gz'
                with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT) as tf:
                    for root in m.ROOTS:
                        item = tarfile.TarInfo(root)
                        item.type = tarfile.DIRTYPE
                        tf.addfile(item)
                    item = tarfile.TarInfo(name)
                    item.type, item.linkname = kind, target
                    tf.addfile(item)
                with self.assertRaises(ValueError):
                    m.validate_archive(archive, self.root)

    def test_archive_cannot_write_through_system_link(self):
        m = self.module()
        self.cache.mkdir()
        archive = self.cache / 'bootstrap.tar.gz'
        with tarfile.open(archive, 'w:gz') as tf:
            for name in m.ROOTS:
                item = tarfile.TarInfo(name)
                item.type = tarfile.DIRTYPE
                tf.addfile(item)
            item = tarfile.TarInfo('build_dir/host/external')
            item.type, item.linkname = tarfile.SYMTYPE, '/usr/bin'
            tf.addfile(item)
            tf.addfile(tarfile.TarInfo('build_dir/host/external/do-not-write'))
        with self.assertRaises(ValueError):
            m.validate_archive(archive, self.root)

    def test_config_mode_builder_path_host_and_environment_invalidate(self):
        m = self.module()
        a = m.key(self.root, 'builder', 'tc')
        self.assertNotEqual(a, m.key(self.root, 'builder-two', 'tc'))
        with patch.dict(os.environ, {'LANG': 'different'}):
            self.assertNotEqual(a, m.key(self.root, 'builder', 'tc'))
        old = os.uname()
        with patch.object(m.os, 'uname', return_value=os.uname_result((old.sysname, old.nodename, old.release, old.version, 'another-arch'))):
            self.assertNotEqual(a, m.key(self.root, 'builder', 'tc'))
        copied = self.root.parent / 'another-path'
        shutil.copytree(self.root, copied)
        self.assertNotEqual(a, m.key(copied, 'builder', 'tc'))
        p = self.root / 'tools/Makefile'
        p.chmod(0o755)
        self.assertNotEqual(a, m.key(self.root, 'builder', 'tc'))
        p.chmod(0o644)
        self.assertEqual(a, m.key(self.root, 'builder', 'tc'))
        (self.root / '.config').write_text('# Generated\nCONFIG_CCACHE=y\nCONFIG_PACKAGE_example=y\n')
        self.assertNotEqual(a, m.key(self.root, 'builder', 'tc'))

    def test_key_does_not_touch_completion_stamps(self):
        m = self.module()
        ns = self.artifacts()
        m.key(self.root, 'builder', 'tc')
        self.assertEqual((self.root / 'build_dir/host/ccache-1.0/.built').stat().st_mtime_ns, ns)
        self.assertEqual((self.root / 'tools/Makefile').stat().st_mtime_ns, m.EPOCH * 1_000_000_000)

    def test_invalid_config_or_external_inputs_fail_closed(self):
        m = self.module()
        for data in ('include /outside\n', 'CONFIG_A="$(shell id)"\n',
                     'CONFIG_A=y\nCONFIG_A=m\n', 'CONFIG_EXTERNAL_TOOLCHAIN=y\n',
                     'CONFIG_SRC_TREE_OVERRIDE=y\n', 'CONFIG_EXTERNAL_KERNEL_TREE="/external"\n'):
            with self.subTest(data=data):
                (self.root / '.config').write_text(data)
                with self.assertRaises(ValueError):
                    m.key(self.root, 'builder', 'tc')
        (self.root / '.config').unlink()
        with self.assertRaises(ValueError):
            m.key(self.root, 'builder', 'tc')

    def test_plain_host_optimization_flags_are_key_inputs(self):
        m = self.module()
        a = m.key(self.root, 'builder', 'tc')
        (self.root / '.config').write_text('CONFIG_CCACHE=y\nCONFIG_HOST_EXTRA_CFLAGS="-O3 -pipe"\n')
        self.assertNotEqual(a, m.key(self.root, 'builder', 'tc'))
        (self.root / '.config').write_text('CONFIG_HOST_EXTRA_CFLAGS="-include /mutable/header.h"\n')
        with self.assertRaises(ValueError):
            m.key(self.root, 'builder', 'tc')

    def test_link_target_parent_chain_cannot_hide_escape(self):
        m = self.module()
        self.cache.mkdir()
        archive = self.cache / 'bootstrap.tar.gz'
        with tarfile.open(archive, 'w:gz') as tf:
            for name in m.ROOTS:
                item = tarfile.TarInfo(name)
                item.type = tarfile.DIRTYPE
                tf.addfile(item)
            for name, target in (
                    ('staging_dir/host/alias', '/usr/bin'),
                    ('staging_dir/host/indirect', 'alias/../etc/passwd')):
                item = tarfile.TarInfo(name)
                item.type, item.linkname = tarfile.SYMTYPE, target
                tf.addfile(item)
        with self.assertRaises(ValueError):
            m.validate_archive(archive, self.root)

    def test_config_permission_change_misses(self):
        m = self.module()
        a = m.key(self.root, 'builder', 'tc')
        (self.root / '.config').chmod(0o600)
        self.assertNotEqual(a, m.key(self.root, 'builder', 'tc'))

    def test_empty_config_fails_closed(self):
        m = self.module()
        (self.root / '.config').write_text('# no generated settings\n')
        with self.assertRaises(ValueError):
            m.key(self.root, 'builder', 'tc')

    def test_internal_key_record_must_match_exactly(self):
        m = self.module()
        self.artifacts()
        m.pack(self.root, self.cache, 'tb-one')
        (self.cache / 'key').write_text(' tb-one \n')
        with self.assertRaises(ValueError):
            m.restore(self.root, self.cache, 'tb-one')

    def test_rust_tool_selectors_remain_toolchain_bound(self):
        m = self.module()
        setattr(m, 'REVIEWED', {m.inventory(self.root)})
        original = (self.root / '.config').read_bytes()
        # tools/Makefile admits these branches; rust-values/host-build inputs
        # are outside FIXED_INPUTS. Explicit n is nonempty to GNU make too.
        for name in ('BUILD_ALL_HOST_TOOLS', 'USE_RUST_TOOLCHAIN', 'USE_RUST_BUILD',
                     'USE_RUST_PREBUILT', 'USE_RUST_HOST', 'BUILD_BINDGEN',
                     'USE_CBINDGEN', 'USE_CORROSION', 'RUST_SCCACHE'):
            for value in ('y', 'm', 'n'):
                with self.subTest(selector=name, value=value):
                    (self.root / '.config').write_bytes(
                        original + f'CONFIG_{name}={value}\n'.encode())
                    self.assertNotEqual(m.key(self.root, 'builder', 'tc-one'),
                                        m.key(self.root, 'builder', 'tc-two'))
        (self.root / '.config').write_bytes(
            original + b'CONFIG_RUST_TOOLCHAIN_HOST_PATH="/unlocked/rust"\n')
        self.assertNotEqual(m.key(self.root, 'builder', 'tc-one'),
                            m.key(self.root, 'builder', 'tc-two'))

    def test_all_external_selectors_and_override_escapes_reject(self):
        m = self.module()
        setattr(m, 'REVIEWED', {m.inventory(self.root)})
        config = self.root / '.config'
        original = config.read_bytes()
        for name in ('EXTERNAL_TOOLCHAIN', 'SRC_TREE_OVERRIDE', 'NATIVE_TOOLCHAIN', 'SDK'):
            config.write_bytes(original + f'CONFIG_{name}=y\n'.encode())
            with self.subTest(selector=name), self.assertRaises(ValueError):
                m.key(self.root, 'builder', 'tc')
        for name in ('EXTERNAL_KERNEL_TREE', 'TOOLCHAIN_ROOT', 'TOOLCHAIN_BIN_PATH',
                     'TOOLCHAIN_INC_PATH', 'TOOLCHAIN_LIB_PATH', 'DOWNLOAD_TOOL_CUSTOM',
                     'DOWNLOAD_FOLDER', 'BUILD_SUFFIX'):
            config.write_bytes(original + f'CONFIG_{name}="/unlocked"\n'.encode())
            with self.subTest(selector=name), self.assertRaises(ValueError):
                m.key(self.root, 'builder', 'tc')
        config.write_bytes(original)
        for name in m.OVERRIDES:
            with self.subTest(override=name), patch.dict(os.environ, {name: '/unlocked'}):
                with self.assertRaises(ValueError):
                    m.key(self.root, 'builder', 'tc')
        self.assertIn('CONFIGURE_CACHE_DIR', m.OVERRIDES)
        for name in m.ESCAPES:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# unreviewed include/source\n')
            with self.subTest(escape=name), self.assertRaises(ValueError):
                m.key(self.root, 'builder', 'tc')
            p.unlink()

    def test_config_site_base_environment_override_rejects_explicitly(self):
        m = self.module()
        setattr(m, 'REVIEWED', {m.inventory(self.root)})
        # Independent of OVERRIDES: the native site/cache sources this file.
        with patch.dict(os.environ, {'CONFIG_SITE_BASE': ''}):
            baseline = m.key(self.root, 'builder', 'tc-one')
            self.assertEqual(baseline, m.key(self.root, 'builder', 'tc-two'))
        site = self.root.parent / 'external.site'
        site.write_text('ac_cv_external_input=first\n')
        for value in (str(site), str(self.root.parent / 'missing.site'), ' '):
            with self.subTest(value=value), patch.dict(os.environ, {'CONFIG_SITE_BASE': value}):
                with self.assertRaisesRegex(ValueError, 'environment overrides'):
                    m.key(self.root, 'builder', 'tc-one')
        site.write_text('ac_cv_external_input=changed\n')
        with patch.dict(os.environ, {'CONFIG_SITE_BASE': str(site)}):
            with self.assertRaisesRegex(ValueError, 'environment overrides'):
                m.key(self.root, 'builder', 'tc-two')

    def test_unknown_source_binds_full_toolchain_key(self):
        a = self.cli('key', self.root, self.cache, 'builder', 'tc-one')
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertRegex(a.stdout, r'^[0-9a-f]{64}\n$')
        b = self.cli('key', self.root, self.cache, 'builder', 'tc-two')
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertNotEqual(a.stdout, b.stdout)


@unittest.skipUnless(os.environ.get('BOOTSTRAP_SOURCE'), 'requires customized source')
class PreparedBootstrapTests(unittest.TestCase):
    def test_current_customized_inventory_matches_expected_contract(self):
        spec = importlib.util.spec_from_file_location('prepared_bootstrap', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        root = Path(os.environ['BOOTSTRAP_SOURCE'])
        assert_prepared_contract(self, module, root)

    def test_real_cli_lock_mutations_and_safe_fallbacks(self):
        spec = importlib.util.spec_from_file_location('prepared_bootstrap_cli', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = Path(os.environ['BOOTSTRAP_SOURCE'])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            root.mkdir()
            for name in ('tools', 'scripts'):
                shutil.copytree(source / name, root / name, symlinks=True)
            for name in (*module.FIXED_INPUTS, '.config', '.external-packages.mk'):
                src, dst = source / name, root / name
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            expected = assert_prepared_contract(self, module, root)

            def cli(tc='tc-one', builder='builder', updates=None, fails=None):
                env = dict(os.environ)
                env.update(updates or {})
                result = subprocess.run([sys.executable, str(SCRIPT), 'key', str(root),
                                         str(Path(tmp) / 'cache'), builder, tc],
                                        env=env, capture_output=True, text=True)
                if fails:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(fails, result.stderr)
                    self.assertEqual(result.stdout, '')
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertRegex(result.stdout, r'^[0-9a-f]{64}\n$')
                return result

            baseline = cli().stdout
            if expected == 'reviewed-independent':
                self.assertEqual(baseline, cli('tc-two').stdout)
            else:
                self.assertNotEqual(baseline, cli('tc-two').stdout)
            self.assertIn(expected, cli().stderr)
            self.assertNotEqual(baseline, cli(builder='different').stdout)
            self.assertNotEqual(baseline, cli(updates={'LANG': 'changed'}).stdout)
            cli(updates={'CONFIGURE_CACHE_DIR': '/unlocked'},
                fails='environment overrides')
            self.assertEqual(baseline, cli(updates={'CONFIG_SITE_BASE': ''}).stdout)
            site = Path(tmp) / 'external.site'
            for content in ('ac_cv_external_input=first\n', 'ac_cv_external_input=changed\n'):
                site.write_text(content)
                for tc in ('tc-one', 'tc-two'):
                    with self.subTest(override='CONFIG_SITE_BASE', tc=tc, content=content):
                        cli(tc, updates={'CONFIG_SITE_BASE': str(site)},
                            fails='environment overrides')

            def bound():
                a, b = cli(), cli('tc-two')
                self.assertNotEqual(a.stdout, baseline)
                self.assertNotEqual(a.stdout, b.stdout)
                self.assertIn('full-toolchain-bound', a.stderr)

            for name in ('tools/ccache/Makefile', 'scripts/download.pl',
                         'scripts/projectsmirrors.json', 'include/host-build.mk',
                         'include/site/cache', 'include/rootfs.mk', 'package/Makefile',
                         '.external-packages.mk'):
                p = root / name
                if name not in (*module.FIXED_INPUTS, '.external-packages.mk'):
                    self.assertTrue(p.is_file(), f'missing required producer input: {name}')
                original = p.read_bytes() if p.exists() else None
                mode = p.stat().st_mode & 0o777 if original is not None else 0o644
                # Fixed inputs also lock absence (e.g. stable has no site/cache).
                mutations = ('content', 'mode', 'missing') if original is not None else ('present',)
                for mutation in mutations:
                    with self.subTest(input=name, mutation=mutation):
                        try:
                            if mutation in ('content', 'present'):
                                p.parent.mkdir(parents=True, exist_ok=True)
                                p.write_bytes((original or b'') + b'\n# unknown source\n')
                            elif mutation == 'mode':
                                p.chmod(mode ^ 0o100)
                            else:
                                p.unlink()
                            bound()
                        finally:
                            if original is None:
                                p.unlink()
                            else:
                                p.write_bytes(original)
                                p.chmod(mode)
                self.assertEqual(baseline, cli().stdout)
            p = root / '.external-packages.mk'
            original = p.read_bytes() if p.exists() else None
            mode = p.stat().st_mode & 0o777 if original is not None else 0o644
            p.unlink(missing_ok=True)
            p.symlink_to(root / 'tools/Makefile')
            cli(fails='nonregular external make input')
            p.unlink()
            p.mkdir()
            cli(fails='nonregular external make input')
            p.rmdir()
            if original is not None:
                p.write_bytes(original)
                p.chmod(mode)
            cfg = root / '.config'
            original, mode = cfg.read_bytes(), cfg.stat().st_mode & 0o777

            def set_config(name, value):
                # Real final configs can already contain an unset/assigned row.
                lines = [line for line in original.splitlines(keepends=True)
                         if not line.startswith((f'CONFIG_{name}='.encode(),
                                                 f'# CONFIG_{name} is not set'.encode()))]
                cfg.write_bytes(b''.join(lines) + f'CONFIG_{name}={value}\n'.encode())

            try:
                for name in ('EXTERNAL_TOOLCHAIN', 'SRC_TREE_OVERRIDE', 'NATIVE_TOOLCHAIN', 'SDK'):
                    with self.subTest(rejected_selector=name):
                        set_config(name, 'y')
                        cli(fails='external/mutable bootstrap input')
                for name in ('EXTERNAL_KERNEL_TREE', 'TOOLCHAIN_ROOT', 'TOOLCHAIN_BIN_PATH',
                             'TOOLCHAIN_INC_PATH', 'TOOLCHAIN_LIB_PATH', 'DOWNLOAD_TOOL_CUSTOM',
                             'DOWNLOAD_FOLDER', 'BUILD_SUFFIX'):
                    with self.subTest(rejected_path=name):
                        set_config(name, '"/unlocked"')
                        cli(fails='unlocked external input')
                set_config('BOOTSTRAP_BOUNDARY_TEST', 'y')
                self.assertNotEqual(baseline, cli().stdout)
                cfg.write_bytes(original)
                cfg.chmod(0o600 if mode != 0o600 else 0o644)
                self.assertNotEqual(baseline, cli().stdout)
                cfg.chmod(mode)
                for name in module.BOUND_SELECTORS:
                    for value in ('y', 'm', 'n'):
                        with self.subTest(selector=name, value=value):
                            set_config(name, value)
                            bound()
                set_config('RUST_TOOLCHAIN_HOST_PATH', '"/unlocked/rust"')
                bound()
                # Rust make includes are deliberately outside the reviewed lock;
                # changing one must not bypass the selector's full-key binding.
                p = root / 'include/rust-values.mk'
                p.write_text('include /unreviewed/rust.mk\n')
                set_config('USE_RUST_TOOLCHAIN', 'y')
                bound()
                p.unlink()
            finally:
                cfg.write_bytes(original)
                cfg.chmod(mode)
            self.assertEqual(baseline, cli().stdout)

    def test_prepared_lock_keeps_source_config_and_environment_boundaries(self):
        spec = importlib.util.spec_from_file_location('prepared_bootstrap_boundaries', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = Path(os.environ['BOOTSTRAP_SOURCE'])
        # Copy only audited inputs, never an entire build tree or its artifacts.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            root.mkdir()
            def ignored_generated(directory, names):
                return [name for name in names
                        if (Path(directory) / name).relative_to(source).as_posix().startswith('scripts/config/')
                        and subprocess.run(['git', 'check-ignore', '-q', '--',
                                            str((Path(directory) / name).relative_to(source))],
                                           cwd=source, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL).returncode == 0]

            for name in ('tools', 'scripts'):
                shutil.copytree(source / name, root / name, symlinks=True,
                                ignore=ignored_generated)
            for name in (*module.FIXED_INPUTS, '.config', '.external-packages.mk'):
                src, dst = source / name, root / name
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            assert_prepared_contract(self, module, root)
            baseline = module.key(root, 'builder', 'tc-one')
            baseline_other_tc = module.key(root, 'builder', 'tc-two')
            # These later world/runtime inputs do not produce the early snapshot.
            for name in ('target/linux/bootstrap-test.patch', 'files/etc/bootstrap-test',
                         '.external-packages/eamonxg/packages.adb'):
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('# not an early host producer\n')
                self.assertEqual(baseline, module.key(root, 'builder', 'tc-one'))
                self.assertEqual(baseline_other_tc, module.key(root, 'builder', 'tc-two'))
            for name in ('tools/ccache/Makefile', 'scripts/download.pl', 'include/rootfs.mk',
                         '.external-packages.mk'):
                p = root / name
                original = p.read_bytes() if p.exists() else None
                with self.subTest(input=name):
                    try:
                        p.write_bytes((original or b'') + b'\n# unknown producer inventory\n')
                        self.assertNotEqual(baseline, module.key(root, 'builder', 'tc-one'))
                        self.assertNotEqual(module.key(root, 'builder', 'tc-one'),
                                            module.key(root, 'builder', 'tc-two'))
                    finally:
                        if original is None:
                            p.unlink()
                        else:
                            p.write_bytes(original)
            p = root / 'tools/ccache/Makefile'
            original_mode = p.stat().st_mode & 0o777
            p.chmod(original_mode ^ 0o100)
            self.assertNotEqual(module.key(root, 'builder', 'tc-one'),
                                module.key(root, 'builder', 'tc-two'))
            p.chmod(original_mode)
            cfg = root / '.config'
            original = cfg.read_bytes()
            try:
                cfg.write_bytes(original + b'\nCONFIG_BOOTSTRAP_BOUNDARY_TEST=y\n')
                self.assertNotEqual(baseline, module.key(root, 'builder', 'tc-one'))
                # Even a reviewed inventory cannot project BUILD_ALL_HOST_TOOLS.
                cfg.write_bytes(original + b'\nCONFIG_BUILD_ALL_HOST_TOOLS=y\n')
                self.assertNotEqual(module.key(root, 'builder', 'tc-one'),
                                    module.key(root, 'builder', 'tc-two'))
            finally:
                cfg.write_bytes(original)
            self.assertEqual(baseline, module.key(root, 'builder', 'tc-one'))
            self.assertNotEqual(baseline, module.key(root, 'different-builder', 'tc-one'))
            with patch.dict(os.environ, {'LANG': 'bootstrap-test-language'}):
                self.assertNotEqual(baseline, module.key(root, 'builder', 'tc-one'))
            with patch.dict(os.environ, {'MAKEFILES': '/unreviewed/Makefile'}):
                with self.assertRaises(ValueError):
                    module.key(root, 'builder', 'tc-one')


if __name__ == '__main__':
    unittest.main()
