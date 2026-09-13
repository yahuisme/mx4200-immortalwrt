"""Unpack transaction regressions; production GNU PAX archives."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cache_unpack', Path(__file__).resolve().parents[1] / 'Scripts/Cache.py')
assert spec is not None and spec.loader is not None
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class UnpackOptimization(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.src = self.base / 'src'
        self.dst = self.base / 'dst'
        self.dst.mkdir()
        for name in ('dl', '.ccache'):
            (self.src / name).mkdir(parents=True)
            (self.src / name / 'data').write_bytes(b'actual payload')
            os.utime(self.src / name / 'data', ns=(1600000000123456789, 1600000000123456789))
            (self.dst / name).mkdir()
            (self.dst / name / 'original').write_text('keep')
        self.archive = self.base / 'cache.tgz'
        cache.pack(self.src, 'rolling', self.archive)

    def assert_clean(self):
        self.assertEqual(sorted(p.name for p in self.dst.iterdir()), ['.ccache', 'dl'])

    def assert_original(self):
        self.assert_clean()
        for name in ('dl', '.ccache'):
            self.assertEqual([p.name for p in (self.dst / name).iterdir()], ['original'])

    def test_pax_roundtrip(self):
        cache.unpack(self.dst, 'rolling', self.archive)
        self.assert_clean()
        for name in ('dl', '.ccache'):
            p = self.dst / name / 'data'
            self.assertEqual(p.read_bytes(), b'actual payload')
            self.assertEqual(p.stat().st_mtime_ns, 1600000000123456789)

    def test_corrupt_compression_preserves_destination(self):
        self.archive.write_bytes(self.archive.read_bytes()[:30])
        with self.assertRaises(Exception):
            cache.unpack(self.dst, 'rolling', self.archive)
        self.assert_original()

    def test_validation_error_preserves_destination(self):
        with tarfile.open(self.archive, 'w:gz') as tf:
            tf.add(self.src / 'dl', arcname='../escape')
        with self.assertRaises(ValueError):
            cache.unpack(self.dst, 'rolling', self.archive)
        self.assert_original()

    def test_real_extraction_failure_rolls_back(self):
        real_run = subprocess.run
        extracted = []
        def fail_after_extract(args, **kwargs):
            if args[0] == 'tar' and any(str(a).startswith('-x') for a in args):
                # GNU tar restores real members, then exits 2 for a missing member.
                try:
                    return real_run(args + ['--', 'dl', '.ccache', 'missing-member'], **kwargs)
                finally:
                    self.assertTrue((self.dst / 'dl/data').exists())
                    self.assertFalse((self.dst / 'dl/original').exists())
                    extracted.append(True)
            return real_run(args, **kwargs)
        with patch.object(cache.subprocess, 'run', side_effect=fail_after_extract):
            with self.assertRaises(subprocess.CalledProcessError):
                cache.unpack(self.dst, 'rolling', self.archive)
        self.assertEqual(extracted, [True])
        self.assert_original()


if __name__ == '__main__':
    unittest.main()
