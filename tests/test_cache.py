import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'Scripts/Cache.py'


class CacheTest(unittest.TestCase):
    def test_fresh_checkout_and_changed_input(self):
        self.assertTrue(SCRIPT.exists(), 'Cache input normalization is missing')
        spec = importlib.util.spec_from_file_location('cache', SCRIPT)
        assert spec is not None and spec.loader is not None
        cache = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cache)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in cache.INPUTS:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(name)
            stamp = root / 'build_dir/host/test/.built'
            stamp.parent.mkdir(parents=True)
            stamp.touch()
            timestamp = stamp.stat().st_mtime_ns
            key = cache.cache_key(root, 'host-a')
            for name in cache.INPUTS:
                os.utime(root / name, None)
            self.assertEqual(key, cache.cache_key(root, 'host-a'))
            self.assertEqual(timestamp, stamp.stat().st_mtime_ns)
            self.assertEqual((root / 'tools').stat().st_mtime, cache.EPOCH)
            self.assertNotEqual(key, cache.cache_key(root, 'host-b'))
            (root / 'tools').write_text('updated recipe')
            self.assertNotEqual(key, cache.cache_key(root, 'host-a'))
            changed = cache.cache_key(root, 'host-a')
            (root / 'tools').chmod(0o755)
            self.assertNotEqual(changed, cache.cache_key(root, 'host-a'))
            (root / 'scripts').unlink()
            generated = root / 'scripts/config/conf'
            generated.parent.mkdir(parents=True)
            (generated.parent / 'Makefile').write_text('recipe')
            stable = cache.cache_key(root, 'host-a')
            generated.write_text('generated binary')
            self.assertEqual(stable, cache.cache_key(root, 'host-a'))
            (generated.parent / 'parser.o').write_text('object')
            self.assertEqual(stable, cache.cache_key(root, 'host-a'))
            (root / 'tools').unlink()
            (root / 'tools').symlink_to(generated.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                cache.cache_key(root, 'host-a')
            (root / 'tools').unlink()
            with self.assertRaises(ValueError):
                cache.cache_key(root, 'host-a')


if __name__ == '__main__':
    unittest.main()
