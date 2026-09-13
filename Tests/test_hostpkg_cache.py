import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HostpkgTests(unittest.TestCase):
    def test_archive_tier_and_budget(self):
        from Scripts import Cache
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('build_dir/hostpkg', 'staging_dir/hostpkg'):
                (root / name).mkdir(parents=True)
            self.assertEqual(Cache.paths(root, 'hostpkg'), ['build_dir/hostpkg', 'staging_dir/hostpkg'])
            self.assertTrue(Cache.allowed('build_dir/hostpkg/.built', 'hostpkg'))
            self.assertFalse(Cache.allowed('build_dir/host/.built', 'hostpkg'))
            with tempfile.TemporaryDirectory() as archives:
                archive = Path(archives) / 'hostpkg.tar.gz'
                stamp = root / 'build_dir/hostpkg/.built'
                stamp.write_text('real archive fixture')
                before = stamp.stat().st_mtime_ns
                Cache.pack(root, 'hostpkg', archive)
                stamp.unlink()
                Cache.unpack(root, 'hostpkg', archive)
                self.assertEqual(stamp.stat().st_mtime_ns, before)
                self.assertEqual(stamp.read_text(), 'real archive fixture')
            key = Cache.scope('refs/heads/main') + 'hostpkg-abc'
            self.assertTrue(Cache.admission([], 100, key, 'refs/heads/main')['admitted'])
            self.assertFalse(Cache.admission([{'size_in_bytes': Cache.LIMIT, 'key': 'unrelated', 'ref': 'refs/heads/other'}], 100, key, 'refs/heads/main')['admitted'])

    def test_content_inventory_and_exact_metadata_exclusion(self):
        script = ROOT / 'Scripts/HostpkgCache.py'
        self.assertTrue(script.is_file(), 'hostpkg fingerprint helper missing')
        spec = importlib.util.spec_from_file_location('hostpkg', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('package/feeds', 'feeds/packages/nested', 'feeds/packages.tmp/info', 'bootstrap/bin', 'build_dir/hostpkg'):
                (root / name).mkdir(parents=True)
            (root / 'package/feeds/pkg').symlink_to('../../feeds/packages/nested', target_is_directory=True)
            source = root / 'feeds/packages/nested/Makefile'
            source.write_text('recipe')
            (root / 'bootstrap/bin/go').write_bytes(b'bootstrap')
            stamp = root / 'build_dir/hostpkg/.built'
            stamp.touch()
            stamp_ns = stamp.stat().st_mtime_ns
            def key(tc='tc-original'):
                return module.cache_key(root, tc, root / 'bootstrap')
            original = key()
            (root / 'feeds/packages.tmp/info/random-pid').write_text('generated')
            (root / 'feeds/packages.index').write_text('random cookie')
            self.assertEqual(key(), original)
            self.assertEqual(stamp.stat().st_mtime_ns, stamp_ns)
            self.assertEqual(source.stat().st_mtime_ns, module.EPOCH_NS)
            self.assertNotEqual(key('tc-changed'), original)
            source.write_text('changed')
            self.assertNotEqual(key(), original)
            source.write_text('recipe')
            (root / 'feeds/packages/nested/input.tmp').write_text('real source')
            self.assertNotEqual(key(), original)
            (root / 'feeds/packages/nested/input.tmp').unlink()
            (root / 'feeds/orphan.tmp').write_text('real source')
            self.assertNotEqual(key(), original)
            (root / 'feeds/orphan.tmp').unlink()
            (root / 'bootstrap/bin/go').write_bytes(b'changed bootstrap')
            self.assertNotEqual(key(), original)
            (root / 'package/bad').symlink_to('../feeds/packages.tmp/info/random-pid')
            with self.assertRaises(ValueError):
                key()
