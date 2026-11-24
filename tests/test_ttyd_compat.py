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
    def test_copy_is_repeatable_and_scoped_to_reviewed_ttyd_source(self):
        for case in ('known', 'unknown', 'conflict'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                recipe = Path(tmp) / 'feeds/packages/utils/ttyd'
                (recipe / 'patches').mkdir(parents=True)
                makefile = recipe / 'Makefile'
                version = '2.0.0' if case == 'unknown' else '1.7.7'
                original = f'PKG_VERSION:={version}\nPKG_RELEASE:=1\nPKG_HASH:={SOURCE_HASH}\n'
                makefile.write_text(original)
                other = recipe / 'patches/100-log-to-syslog.patch'
                other.write_text('native logging patch\n')
                staged = recipe / 'patches' / PATCH
                if case == 'conflict':
                    staged.write_text('different patch\n')
                for _ in range(2):
                    result = subprocess.run(['bash', str(HOOK), tmp], text=True, capture_output=True)
                    if case == 'known':
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(staged.read_bytes(), (ROOT / 'scripts/ttyd-patches' / PATCH).read_bytes())
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('ttyd', result.stderr)
                        self.assertEqual(staged.exists(), case == 'conflict')
                        if case == 'conflict':
                            self.assertEqual(staged.read_text(), 'different patch\n')
                    self.assertEqual(makefile.read_text(), original)
                    self.assertEqual(other.read_text(), 'native logging patch\n')
