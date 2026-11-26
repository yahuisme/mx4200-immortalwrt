"""Replay the actual ttyd recipe hook without compiling firmware."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'scripts/ttyd_compat.sh'
PATCH = '110-run-libuv-loop.patch'
SOURCE_HASH = '039dd995229377caee919898b7bd54484accec3bba49c118e2d5cd6ec51e3650'


class TtydCompatTests(unittest.TestCase):
    def test_copy_and_revision_are_repeatable_and_scoped(self):
        patch = (ROOT / 'scripts/ttyd-patches' / PATCH).read_bytes()
        original = f'PKG_VERSION:=1.7.7\nPKG_RELEASE:=1\nPKG_HASH:={SOURCE_HASH}\n'
        local = original.replace('PKG_RELEASE:=1', 'PKG_RELEASE:=2')
        for label, recipe_text, existing, error in (
                ('fresh', original, None, None),
                ('old patched cache', original, patch, None),
                ('local', local, patch, None),
                ('upstream changed release', local, None, 'unreviewed package release'),
                ('repeated assignment', original + 'PKG_RELEASE:=3\n', None, 'unreviewed package release'),
                ('unknown source', original.replace('1.7.7', '1.7.8'), None, 'unreviewed source'),
                ('unknown hash', original.replace(SOURCE_HASH, '0' * 64), None, 'unreviewed source'),
                ('missing source fields', 'PKG_RELEASE:=1\n', None, 'unreviewed source'),
                ('duplicate version', original + 'PKG_VERSION = 1.7.8\n', None, 'unreviewed source'),
                ('duplicate hash', original + 'PKG_HASH := ' + '0' * 64 + '\n', None, 'unreviewed source'),
                ('qualified version', original + 'override export PKG_VERSION := 1.7.7\n', None, 'unreviewed source'),
                ('qualified hash', original + f'override PKG_HASH := {SOURCE_HASH}\n', None, 'unreviewed source'),
                ('unexported hash', original + f'unexport PKG_HASH := {SOURCE_HASH}\n', None, 'unreviewed source'),
                ('qualified release', original + 'override PKG_RELEASE := 1\n', None, 'unreviewed package release'),
                ('unexported override', original + 'override unexport PKG_RELEASE := 1\n', None, 'unreviewed package release'),
                ('conflict', original, b'foreign patch', 'conflicting compatibility patch')):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                recipe = Path(tmp) / 'feeds/packages/utils/ttyd'
                (recipe / 'patches').mkdir(parents=True)
                makefile = recipe / 'Makefile'
                makefile.write_text(recipe_text)
                native = recipe / 'patches/100-log-to-syslog.patch'
                native.write_text('native logging patch\n')
                staged = recipe / 'patches' / PATCH
                if existing is not None:
                    staged.write_bytes(existing)
                for _ in range(2):
                    result = subprocess.run(['bash', str(HOOK), tmp], text=True, capture_output=True)
                    if error is None:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(staged.read_bytes(), patch)
                        self.assertEqual(makefile.read_text(), local)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(error, result.stderr)
                        self.assertEqual(staged.read_bytes() if staged.exists() else None, existing)
                        self.assertEqual(makefile.read_text(), recipe_text)
                    self.assertEqual(native.read_text(), 'native logging patch\n')
