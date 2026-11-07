"""HomeWRK excludes Advanced Reboot through native per-device packaging."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import installed_rootfs

ROOT = Path(__file__).resolve().parents[1]
APP = 'luci-app-advanced-reboot'
TRANSLATION = 'luci-i18n-advanced-reboot-zh-cn'
SYMBOL = 'CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq807x_DEVICE_linksys_homewrk'


class HomewrkPackagesTests(unittest.TestCase):
    def assert_installed_packages(self, root, device):
        db = root / 'lib/apk/db/installed'
        self.assertTrue(db.is_file(), str(db))
        names = set(re.findall(r'^P:(.+)$', db.read_text(), re.M))
        self.assertIn('base-files', names, 'not an installed APK database')
        if device == 'homewrk':
            self.assertTrue({APP, TRANSLATION}.isdisjoint(names), names & {APP, TRANSLATION})
            # Check paths independently of the database: per-device removal
            # followed by common files/ could otherwise resurrect orphan files.
            residuals = [str(path.relative_to(root)) for path in root.rglob('*')
                         if 'advanced-reboot' in path.name]
            self.assertEqual(residuals, [], 'HomeWRK Advanced Reboot residue')
        else:
            self.assertTrue({APP, TRANSLATION} <= names, 'supported model lost Advanced Reboot')
            for rel in (
                f'usr/share/luci/menu.d/{APP}.json',
                f'usr/share/rpcd/acl.d/{APP}.json',
                'www/luci-static/resources/view/system/advanced-reboot.js',
                'usr/lib/lua/luci/i18n/advanced-reboot.zh-cn.lmo',
            ):
                self.assertTrue((root / rel).is_file(), rel)

    def test_actual_installed_packages(self):
        selected = installed_rootfs.roots()
        if not selected:
            self.skipTest('set MX_ROOTFS_BASE or MX_MENU_ROOT + MX_MENU_DEVICE')
        for device, root in selected:
            with self.subTest(device=device):
                self.assert_installed_packages(root, device)

    def test_homewrk_package_and_file_residuals_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'lib/apk/db/installed'
            db.parent.mkdir(parents=True)
            db.write_text('P:base-files\nV:1\n\n')
            self.assert_installed_packages(root, 'homewrk')
            for name in (APP, TRANSLATION):
                with self.subTest(package=name):
                    db.write_text(f'P:base-files\nV:1\n\nP:{name}\nV:1\n\n')
                    with self.assertRaises(AssertionError):
                        self.assert_installed_packages(root, 'homewrk')
            db.write_text('P:base-files\nV:1\n\n')
            for rel in (
                f'lib/apk/packages/{APP}.list',
                f'lib/apk/packages/{TRANSLATION}.list',
                f'usr/share/luci/menu.d/{APP}.json',
                f'usr/share/rpcd/acl.d/{APP}.json',
                'www/luci-static/resources/view/system/advanced-reboot.js',
                'usr/lib/lua/luci/i18n/advanced-reboot.zh-cn.lmo',
                'usr/share/rpcd/ucode/luci.advanced-reboot',
                'usr/share/advanced-reboot/linksys.json',
            ):
                with self.subTest(residual=rel):
                    path = root / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('residual')
                    with self.assertRaises(AssertionError):
                        self.assert_installed_packages(root, 'homewrk')
                    path.unlink()
                    # Dangling symlinks are residues too.
                    path.symlink_to('absent')
                    with self.assertRaises(AssertionError):
                        self.assert_installed_packages(root, 'homewrk')
                    path.unlink()
                    if path.parent.name == 'advanced-reboot':
                        path.parent.rmdir()

    def test_supported_device_requires_both_packages_and_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'lib/apk/db/installed'
            db.parent.mkdir(parents=True)
            db.write_text('P:base-files\nV:1\n\n')
            with self.assertRaises(AssertionError):
                self.assert_installed_packages(root, 'mx4200v1')
            db.write_text(f'P:base-files\nV:1\n\nP:{APP}\nV:1\n\nP:{TRANSLATION}\nV:1\n\n')
            payloads = [root / rel for rel in (
                f'usr/share/luci/menu.d/{APP}.json',
                f'usr/share/rpcd/acl.d/{APP}.json',
                'www/luci-static/resources/view/system/advanced-reboot.js',
                'usr/lib/lua/luci/i18n/advanced-reboot.zh-cn.lmo',
            )]
            for path in payloads:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('payload')
            self.assert_installed_packages(root, 'mx4200v1')
            for path in payloads:
                with self.subTest(missing=str(path.relative_to(root))):
                    path.unlink()
                    with self.assertRaises(AssertionError):
                        self.assert_installed_packages(root, 'mx4200v1')
                    path.write_text('payload')

    def test_four_device_roots_are_explicit_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for device in ('mx4200v1', 'mx4200v2', 'mx4300', 'homewrk'):
                (base / device / 'fs').mkdir(parents=True)
            with patch.dict(os.environ, {'MX_ROOTFS_BASE': tmp}, clear=True):
                self.assertEqual(dict(installed_rootfs.roots()), {
                    device: base / device / 'fs'
                    for device in ('mx4200v1', 'mx4200v2', 'mx4300', 'homewrk')})
                (base / 'homewrk/fs').rmdir()
                with self.assertRaisesRegex(AssertionError, 'homewrk'):
                    installed_rootfs.roots()

    def test_single_root_requires_explicit_valid_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'MX_MENU_ROOT': tmp}, clear=True):
                with self.assertRaisesRegex(AssertionError, 'MX_MENU_DEVICE'):
                    installed_rootfs.roots()
                os.environ['MX_MENU_DEVICE'] = 'homewrk'
                self.assertEqual(installed_rootfs.roots(), [('homewrk', Path(tmp))])
                os.environ['MX_MENU_DEVICE'] = 'unknown'
                with self.assertRaisesRegex(AssertionError, 'MX_MENU_DEVICE'):
                    installed_rootfs.roots()
                os.environ['MX_ROOTFS_BASE'] = tmp
                with self.assertRaisesRegex(AssertionError, 'either'):
                    installed_rootfs.roots()

    def test_only_homewrk_removes_app_and_translation(self):
        config = (ROOT / 'user/default/config.diff').read_text()
        self.assertIn('CONFIG_PACKAGE_' + APP + '=y', config)
        selections = dict(re.findall(r'^(CONFIG_TARGET_DEVICE_PACKAGES_\S+)="([^"]*)"$', config, re.M))
        self.assertEqual(selections, {SYMBOL: '-' + APP + ' -' + TRANSLATION})
        self.assertIn('CONFIG_TARGET_PER_DEVICE_ROOTFS=y', config)

    def test_shared_overlay_cannot_reintroduce_removed_menu(self):
        self.assertFalse((ROOT / ('user/default/files/usr/share/luci/menu.d/' + APP + '.json')).exists())

    def test_native_menu_order_template_preserves_every_other_field(self):
        row = json.loads((ROOT / 'tests/fixtures/services-menu-contract.json').read_text())['menus'][APP + '.json']
        source = json.loads(row['text'])
        template = json.loads((ROOT / 'user/default/menus' / (APP + '.json')).read_text())
        self.assertEqual(template['admin/system/advanced-reboot']['order'], 91)
        template['admin/system/advanced-reboot']['order'] = source['admin/system/advanced-reboot']['order']
        self.assertEqual(template, source)
