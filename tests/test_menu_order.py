"""Lock complete Nikki metadata and sort the installed Services menu inventory.

The fixture comes from signed-index-verified APK / native installed files, not
from the overlay. Set MX_MENU_ROOT to a verified installed root to compare a
new package snapshot too. Default checks are metadata contracts, not APK trust
verification; refresh the fixture only after native signed-index verification.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MENUS = ROOT / 'user/default/files/usr/share/luci/menu.d'
FIXTURE = ROOT / 'tests/fixtures/nikki-menu-contract.json'
FIXTURE_SHA256 = '0ccf3a90a114d9e21c13eeb769b25d0a553acf984f8cf9ae5758420e9bf9fab3'
PARENT = 'admin/services/nikki'
TERMINAL = 'admin/services/ttyd'


def menu_files(directory):
    return {p.name: json.loads(p.read_text()) for p in sorted(directory.glob('*.json'))}


class MenuOrderTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), FIXTURE_SHA256,
                         'Refresh from authenticated package/installed metadata, not the overlay')
        self.fixture = json.loads(FIXTURE.read_text())
        self.installed = {}
        for name, row in self.fixture['installed_menus'].items():
            data = row['text'].encode()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])
            algorithm = row['checksum_algorithm']
            if algorithm:
                checksum = (hashlib.sha1(data).digest() if algorithm == 'sha1'
                            else hashlib.sha256(data).digest()[:20])
                self.assertEqual('Q1' + base64.b64encode(checksum).decode(), row['checksum'])
            self.installed[name] = json.loads(row['text'])
        self.overlay = menu_files(MENUS)

    def assert_contract(self, overlay, installed):
        upstream = installed['luci-app-nikki.json']
        nikki = copy.deepcopy(overlay['luci-app-nikki.json'])
        self.assertEqual(nikki[PARENT]['order'], 10)
        self.assertEqual(overlay['luci-app-ttyd.json'][TERMINAL]['order'], 11)
        # Only the parent order may differ, including fields added upstream later.
        if 'order' in upstream[PARENT]:
            nikki[PARENT]['order'] = upstream[PARENT]['order']
        else:
            nikki[PARENT].pop('order')
        self.assertEqual(nikki, upstream)
        merged = {}
        # Whole-file overlay replacement, exactly as rootfs installation behaves.
        for entries in (installed | overlay).values():
            merged.update(entries)
        siblings = [(path, row) for path, row in merged.items()
                    if path.startswith('admin/services/') and path.count('/') == 2]
        siblings.sort(key=lambda item: (item[1].get('order', 10000),
                                        item[1].get('title') or item[0]))
        paths = [path for path, _ in siblings]
        i = paths.index(PARENT)
        self.assertEqual(paths[i + 1], TERMINAL, siblings)

    def test_full_upstream_json_and_actual_sibling_adjacency(self):
        self.assertEqual(self.fixture['nikki_package']['version'], '1.26.2-r1')
        self.assertEqual(len(self.installed), 12)
        self.assert_contract(self.overlay, self.installed)

    def test_submenu_mutations_and_new_upstream_fields_are_rejected(self):
        for field, value in [('title', 'Different title'), ('order', -100),
                             ('action', {'type': 'view', 'path': 'wrong'}),
                             ('depends', {'acl': ['wrong']})]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.overlay)
                row = changed['luci-app-nikki.json'][PARENT + '/log']
                self.assertNotEqual(row.get(field), value)
                row[field] = value
                with self.assertRaises(AssertionError):
                    self.assert_contract(changed, self.installed)
        changed = copy.deepcopy(self.installed)
        changed['luci-app-nikki.json'][PARENT + '/log']['new-upstream-field'] = True
        with self.assertRaises(AssertionError):
            self.assert_contract(self.overlay, changed)

    def test_interposed_actual_sibling_is_rejected(self):
        for order in (10, 10.5, 11):
            with self.subTest(order=order):
                changed = copy.deepcopy(self.installed)
                changed['luci-base.json']['admin/services/interposed'] = {
                    'title': 'Nzzz', 'order': order}
                with self.assertRaises(AssertionError):
                    self.assert_contract(self.overlay, changed)

    @unittest.skipUnless(os.environ.get('MX_MENU_ROOT'), 'set MX_MENU_ROOT to a verified installed root')
    def test_actual_installed_root_contract(self):
        directory = Path(os.environ['MX_MENU_ROOT']) / 'usr/share/luci/menu.d'
        self.assertTrue(directory.is_dir())
        self.assert_contract(self.overlay, menu_files(directory))


if __name__ == '__main__':
    unittest.main()
