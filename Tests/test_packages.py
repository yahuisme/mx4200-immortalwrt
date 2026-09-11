"""Source contract tests, not firmware build evidence."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PackageTests(unittest.TestCase):
    def test_git_recipes(self):
        for name in ('qca-nss-drv', 'qca-nss-ecm', 'qca-nss-clients'):
            text = (ROOT/'package/qca-nss'/name/'Makefile').read_text()
            self.assertIn('PKG_SOURCE_PROTO:=git', text)
            self.assertIn('https://git.codelinaro.org/', text)
            self.assertRegex(text, r'PKG_SOURCE_DATE:=\d{4}-\d{2}-\d{2}')
            self.assertRegex(text, r'PKG_SOURCE_VERSION:=[0-9a-f]{7,40}')
            self.assertNotRegex(text, r'(?m)^PKG_HASH\s*[:?+]?=')
            self.assertRegex(text, r'PKG_MIRROR_HASH:=[0-9a-f]{64}')

    def test_firmware_archive(self):
        text = (ROOT/'package/qca-nss/nss-firmware/Makefile').read_text()
        self.assertIn('https://github.com/qosmio/qca-sdk-nss-fw/releases/download/', text)
        self.assertIn('.tar.zst', text)
        self.assertIn('PKG_HASH:=10a4b1e69470db150915cb063525436494b8ae4eebb8b50ea6ad894082d7abb0', text)

    def test_native_download_path(self):
        text = (ROOT/'.github/workflows/MX4200.yml').read_text()
        self.assertIn('make -C /mnt/build_wrt download', text)
        self.assertNotIn('NSSArchives', text)
        self.assertFalse((ROOT/'Config/nss-archives.json').exists())

    def test_mesh_driver_source_branches(self):
        for name, commit in (('qca-nss-drv', '53e5863'), ('qca-nss-clients', 'c4049d1')):
            text = (ROOT/'package/qca-nss'/name/'Makefile').read_text()
            branch = re.search(r'ifeq \(\$\(CONFIG_NSS_FIRMWARE_VERSION_11_4\),y\)\n(.*?)\nendif', text, re.S)
            self.assertIsNotNone(branch, name)
            self.assertIn('PKG_SOURCE_VERSION:=' + commit, branch.group(1))
            self.assertIn('PATCH_DIR:=$(CURDIR)/patches-11.4', branch.group(1))
            self.assertIn('QSDK_VERSION:=11.4.0.5', branch.group(1))
            self.assertRegex(branch.group(1), r'PKG_MIRROR_HASH:=[0-9a-f]{64}')
            config_deps = text.split('PKG_CONFIG_DEPENDS:=', 1)[1].split('\n\n', 1)[0]
            self.assertIn('CONFIG_NSS_FIRMWARE_VERSION_11_4', config_deps)

    def test_mesh_firmware(self):
        text = (ROOT/'Config/MX4200.txt').read_text()
        self.assertIn('CONFIG_NSS_FIRMWARE_VERSION_11_4=y', text)

if __name__ == '__main__':
    unittest.main()
