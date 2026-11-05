"""HomeWRK excludes Advanced Reboot through native per-device packaging."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = 'luci-app-advanced-reboot'
TRANSLATION = 'luci-i18n-advanced-reboot-zh-cn'
SYMBOL = 'CONFIG_TARGET_DEVICE_PACKAGES_qualcommax_ipq807x_DEVICE_linksys_homewrk'


class HomewrkPackagesTests(unittest.TestCase):
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
