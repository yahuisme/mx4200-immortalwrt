import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'Scripts/HostpkgCache.py'


class HostpkgCacheTest(unittest.TestCase):
    def load(self):
        self.assertTrue(SCRIPT.exists(), 'separate exact hostpkg cache is missing')
        spec = importlib.util.spec_from_file_location('hostpkg', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_links_modes_additions_and_git_metadata(self):
        cache = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package').mkdir()
            (root / 'feeds').mkdir()
            recipe = root / 'package/Makefile'
            recipe.write_text('recipe')
            key = cache.cache_key(root, 'tc', 'go')
            (root / 'feeds/.git').mkdir()
            (root / 'feeds/.git/HEAD').write_text('new checkout')
            self.assertEqual(key, cache.cache_key(root, 'tc', 'go'))
            recipe.chmod(0o755)
            self.assertNotEqual(key, cache.cache_key(root, 'tc', 'go'))
            key = cache.cache_key(root, 'tc', 'go')
            (root / 'feeds/patch').write_text('new')
            self.assertNotEqual(key, cache.cache_key(root, 'tc', 'go'))
            (root / 'package/external').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                cache.cache_key(root, 'tc', 'go')

    def test_feed_scan_pid_metadata_does_not_invalidate_sources(self):
        cache = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package').mkdir()
            (root / 'feeds/demo').mkdir(parents=True)
            recipe = root / 'feeds/demo/Makefile'
            recipe.write_text('host recipe')
            metadata = root / 'feeds/demo.tmp'
            (metadata / 'info').mkdir(parents=True)
            (metadata / '.packageinfo').write_text('generated package index')
            (metadata / '.targetinfo').touch()
            (root / 'feeds/demo.index').symlink_to('demo.tmp/.packageinfo')
            (root / 'feeds/demo.targetindex').symlink_to('demo.tmp/.targetinfo')
            cookie = metadata / 'info/.files-packageinfo-1234'
            cookie.write_text('same source list')
            stamp = cookie.stat().st_mtime_ns
            key = cache.cache_key(root, 'tc', 'go')
            self.assertEqual(stamp, cookie.stat().st_mtime_ns)
            cookie.rename(cookie.with_name('.files-packageinfo-5678'))
            (metadata / '.packageinfo').write_text('regenerated index')
            self.assertEqual(key, cache.cache_key(root, 'tc', 'go'))
            recipe.write_text('changed host recipe')
            self.assertNotEqual(key, cache.cache_key(root, 'tc', 'go'))

    def test_metadata_exclusion_does_not_hide_source_or_bootstrap(self):
        cache = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package').mkdir()
            (root / 'feeds/demo/nested.tmp').mkdir(parents=True)
            (root / 'feeds/orphan.tmp').mkdir()
            for relative in ('feeds/demo/nested.tmp/input', 'feeds/orphan.tmp/input',
                             'feeds/demo/source.index'):
                path = root / relative
                key = cache.cache_key(root, 'tc', 'go')
                path.write_text('real source')
                self.assertNotEqual(key, cache.cache_key(root, 'tc', 'go'))
            metadata = root / 'feeds/demo.tmp'
            metadata.mkdir()
            (metadata / 'input').write_text('scan output')
            bootstrap = cache.fingerprint(root, ('feeds',))
            (metadata / 'input').write_text('changed')
            self.assertNotEqual(bootstrap, cache.fingerprint(root, ('feeds',)))
            (root / 'package/unsafe').symlink_to('../feeds/demo.tmp/input')
            with self.assertRaises(ValueError):
                cache.cache_key(root, 'tc', 'go')

    def test_workflow_has_exact_paired_hostpkg_tier(self):
        import yaml
        workflow = yaml.safe_load((SCRIPT.parents[1] / '.github/workflows/MX4200.yml').read_text())
        steps = {s.get('name'): s for s in workflow['jobs']['build']['steps']}
        self.assertIn('Restore hostpkg', steps)
        self.assertNotIn('restore-keys', steps['Restore hostpkg']['with'])
        self.assertIn('hostpkg-admission.outputs.allowed', steps['Save hostpkg']['if'])
        names = list(steps)
        self.assertLess(names.index('Save ccache'), names.index('Admit hostpkg'))
        self.assertLess(names.index('Unpack hostpkg'), names.index('Compile firmware'))

    def test_capacity_counts_all_generations_and_overhead(self):
        cache = self.load()
        self.assertTrue(cache.admitted([{'size_in_bytes': 7_000_000_000}], 1_000_000_000))
        self.assertFalse(cache.admitted([{'size_in_bytes': 9_000_000_000}], 1_000_000_000))
        self.assertFalse(cache.admitted([{'size_in_bytes': 1}], 0))
        with self.assertRaises(ValueError):
            cache.admitted([{'size_in_bytes': -1}], 1)

    def test_key_covers_feed_dependencies_and_preserves_stamps(self):
        cache = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('package/libs/libunistring/Makefile', 'feeds/packages/lang/golang/golang-values.mk'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            (root / 'package/feeds').mkdir()
            (root / 'package/feeds/go').symlink_to('../../feeds/packages/lang/golang')
            stamp = root / 'build_dir/hostpkg/libunistring/.built'
            stamp.parent.mkdir(parents=True)
            stamp.touch()
            before = stamp.stat().st_mtime_ns
            key = cache.cache_key(root, 'toolchain-a', 'bootstrap-a')
            recipe = root / 'package/libs/libunistring/Makefile'
            os.utime(recipe, None)
            self.assertEqual(key, cache.cache_key(root, 'toolchain-a', 'bootstrap-a'))
            self.assertEqual(before, stamp.stat().st_mtime_ns)
            for tc, go in [('toolchain-b', 'bootstrap-a'), ('toolchain-a', 'bootstrap-b')]:
                self.assertNotEqual(key, cache.cache_key(root, tc, go))
            (root / 'feeds/packages/lang/golang/golang-values.mk').write_text('updated')
            self.assertNotEqual(key, cache.cache_key(root, 'toolchain-a', 'bootstrap-a'))


if __name__ == '__main__':
    unittest.main()
