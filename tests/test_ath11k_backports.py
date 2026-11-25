"""Install both default ath11k backports without accepting an unreviewed chain."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import ath11k_backports as hook


class Ath11kBackports(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.recipe = self.root / 'package/kernel/mac80211'
        self.patches = self.recipe / 'patches/ath11k'
        self.patches.mkdir(parents=True)
        self.makefile = self.recipe / 'Makefile'
        self.original = f'PKG_SOURCE_VERSION:=7.2\nPKG_HASH:={hook.SOURCE_HASH}\nPKG_RELEASE:=15\n'
        self.makefile.write_text(self.original)
        self.native = self.patches / '984-native.patch'
        self.native.write_text('native input\n')
        lock = patch.object(hook, 'CHAIN_HASH', hook.chain_hash([self.native]))
        lock.start()
        self.addCleanup(lock.stop)

    def test_installs_both_and_is_repeatable(self):
        for _ in range(2):
            hook.prepare(self.root)
            self.assertEqual(self.makefile.read_text(), self.original.replace(':=15', ':=16'))
            self.assertEqual(self.native.read_text(), 'native input\n')
            self.assertEqual({p.name for p in self.patches.iterdir()}, {self.native.name, *hook.PAYLOAD})
            for name in hook.PAYLOAD:
                self.assertEqual((self.patches / name).read_bytes(), (hook.PATCH_DIR / name).read_bytes())

    def test_rejects_drift_conflicts_and_partial_install_without_writes(self):
        for case in ('native', 'recipe', 'series', 'payload', 'partial'):
            with self.subTest(case=case):
                extra = self.patches / hook.PAYLOAD[0]
                if case == 'native':
                    self.native.write_text('drift\n')
                elif case == 'recipe':
                    self.makefile.write_text(self.original.replace(':=15', ':=17'))
                elif case == 'series':
                    extra = self.patches / 'series'
                    extra.write_text(self.native.name + '\n')
                elif case == 'payload':
                    extra.write_text('foreign patch\n')
                else:
                    extra.write_bytes((hook.PATCH_DIR / extra.name).read_bytes())
                before = {p: p.read_bytes() for p in self.recipe.rglob('*') if p.is_file()}
                with self.assertRaisesRegex(ValueError, 'ath11k'):
                    hook.prepare(self.root)
                self.assertEqual(before, {p: p.read_bytes() for p in self.recipe.rglob('*') if p.is_file()})
                extra.unlink(missing_ok=True)
                self.makefile.write_text(self.original)
                self.native.write_text('native input\n')


if __name__ == '__main__':
    unittest.main()
