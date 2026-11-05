"""Source-grounded Services menu contract; no installed-image/trust claims.

The digest-locked fixture contains complete package-source menu files at exact
Git revisions, not firmware overlays. MX_MENU_ROOT optionally checks an actual
installed root, including all its additional Services siblings.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MENUS = ROOT / 'user/default/files/usr/share/luci/menu.d'
FIXTURE = ROOT / 'tests/fixtures/services-menu-contract.json'
FIXTURE_SHA256 = 'eec8eac2d5a209cdc3a35311d48b619f24a8b449c56a6d69e85ac08b3fd7569b'
PARENT = 'admin/services/homeproxy'
TERMINAL = 'admin/services/ttyd'
PROXY_MENU = 'luci-app-homeproxy.json'
TERMINAL_MENU = 'luci-app-ttyd.json'


def menu_files(directory):
    return {p.name: json.loads(p.read_text()) for p in sorted(directory.glob('*.json'))}


class MenuOrderTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), FIXTURE_SHA256,
                         'Refresh from exact package-source revisions, never the overlay')
        self.fixture = json.loads(FIXTURE.read_text())
        self.source = {}
        for name, row in self.fixture['menus'].items():
            self.assertRegex(row['revision'], r'^[0-9a-f]{40}$')
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(), row['sha256'])
            self.assertTrue(row['path'].endswith('/usr/share/luci/menu.d/' + name))
            self.source[name] = json.loads(row['text'])
        for app in ('aurora', 'cpufreq'):
            row = json.loads((ROOT / f'tests/fixtures/{app}-menu-contract.json').read_text())
            self.assertRegex(row['revision'], r'^[0-9a-f]{40}$')
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(), row['sha256'])
            self.source[f'luci-app-{app}.json'] = json.loads(row['text'])
        self.overlay = menu_files(MENUS)
        # Advanced Reboot's order is installed by its own package, not shared files/.
        self.overlay.update(menu_files(ROOT / 'user/default/menus'))

    def assert_contract(self, overlay, installed):
        # HomeProxy already supplies order 10. A same-name overlay would replace
        # the whole source menu, hiding future submenus, fields and dependencies.
        self.assertNotIn(PROXY_MENU, overlay, 'Use the native HomeProxy menu without an overlay')
        reboot_menu = 'luci-app-advanced-reboot.json'
        reboot_route = 'admin/system/advanced-reboot'
        advanced = copy.deepcopy(overlay[reboot_menu])
        self.assertEqual(advanced[reboot_route]['order'], 91)
        advanced[reboot_route]['order'] = self.source[reboot_menu][reboot_route]['order']
        self.assertEqual(advanced, self.source[reboot_menu],
                         'Advanced Reboot may change only its parent order')
        cpu_menu = 'luci-app-cpufreq.json'
        cpu_route = 'admin/system/cpufreq'
        cpu = copy.deepcopy(overlay[cpu_menu])
        self.assertEqual(cpu[cpu_route]['order'], 89)
        cpu[cpu_route]['order'] = self.source[cpu_menu][cpu_route]['order']
        self.assertEqual(cpu, self.source[cpu_menu], 'CPU Freq may change only its parent order')
        for name, source in self.source.items():
            if name not in (TERMINAL_MENU, reboot_menu, cpu_menu):
                self.assertEqual(installed[name], source, name)
        self.assertIn(installed[reboot_menu], (self.source[reboot_menu], overlay[reboot_menu]))
        self.assertIn(installed[cpu_menu], (self.source[cpu_menu], overlay[cpu_menu]))
        self.assertEqual(installed[PROXY_MENU], self.source[PROXY_MENU])
        self.assertEqual(installed[PROXY_MENU][PARENT]['order'], 10)
        terminal = copy.deepcopy(overlay[TERMINAL_MENU])
        self.assertEqual(terminal[TERMINAL]['order'], 11)
        # The official package places Terminal under System. Preserve the full
        # file while relocating its route prefix to Services, then set order 11.
        upstream = {path.replace('admin/system/ttyd', TERMINAL, 1): row
                    for path, row in self.source[TERMINAL_MENU].items()}
        if 'order' in upstream[TERMINAL]:
            terminal[TERMINAL]['order'] = upstream[TERMINAL]['order']
        else:
            terminal[TERMINAL].pop('order')
        self.assertEqual(terminal, upstream, 'Terminal may change only its route prefix and parent order')
        self.assertIn(installed[TERMINAL_MENU],
                      (self.source[TERMINAL_MENU], overlay[TERMINAL_MENU]))
        merged = {}
        for entries in (installed | overlay).values():
            for path, row in entries.items():
                self.assertNotIn(path, merged, 'Duplicate menu route can clobber package metadata')
                merged[path] = row
        self.assertEqual({p: row for p, row in merged.items()
                          if p == PARENT or p.startswith(PARENT + '/')}, self.source[PROXY_MENU])
        siblings = [(path, row) for path, row in merged.items()
                    if path.startswith('admin/services/') and path.count('/') == 2]
        siblings.sort(key=lambda item: (item[1].get('order', 10000),
                                        item[1].get('title') or item[0]))
        paths = [path for path, _ in siblings]
        i = paths.index(PARENT)
        self.assertEqual(paths[i + 1:i + 2], [TERMINAL], siblings)
        system = sorted((path for path in merged
                         if path.startswith('admin/system/') and path.count('/') == 2),
                        key=lambda path: (merged[path].get('order', 10000),
                                          merged[path].get('title') or path))
        i = system.index(cpu_route)
        self.assertEqual(system[i:i + 4], [cpu_route, 'admin/system/reboot', reboot_route,
                                          'admin/system/aurora'])

    def test_complete_source_menus_and_actual_sibling_adjacency(self):
        expected = {'luci-app-homeproxy.json', 'luci-app-ttyd.json', 'luci-app-wol.json',
                    'luci-app-advanced-reboot.json', 'luci-app-firewall.json',
                    'luci-app-package-manager.json', 'luci-base.json',
                    'luci-mod-network.json', 'luci-mod-status.json', 'luci-mod-system.json',
                    'luci-app-aurora.json', 'luci-app-cpufreq.json'}
        self.assertEqual(set(self.source), expected)
        recipe = (ROOT / 'user/default/config.diff').read_text()
        for package in ('homeproxy', 'ttyd', 'wol', 'advanced-reboot'):
            self.assertIn('CONFIG_PACKAGE_luci-app-' + package + '=y', recipe)
        self.assertEqual(set(self.source[PROXY_MENU]),
                         {PARENT, *(PARENT + '/' + n for n in ('client', 'node', 'server', 'status'))})
        self.assert_contract(self.overlay, self.source)

    def test_same_filename_overlay_and_cross_file_submenu_clobber_are_rejected(self):
        changed = copy.deepcopy(self.overlay)
        changed[PROXY_MENU] = copy.deepcopy(self.source[PROXY_MENU])
        with self.assertRaises(AssertionError):
            self.assert_contract(changed, self.source)
        changed = copy.deepcopy(self.overlay)
        changed['custom.json'] = {PARENT + '/client': {'action': {'type': 'view', 'path': 'wrong'}}}
        with self.assertRaises(AssertionError):
            self.assert_contract(changed, self.source)

    def test_submenu_mutations_and_missing_upstream_fields_are_rejected(self):
        for field, value in [('title', 'Different title'), ('order', -100),
                             ('action', {'type': 'view', 'path': 'wrong'}),
                             ('depends', {'acl': ['wrong']}), ('new-upstream-field', True)]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.source)
                changed[PROXY_MENU][PARENT + '/client'][field] = value
                with self.assertRaises(AssertionError):
                    self.assert_contract(self.overlay, changed)
        changed = copy.deepcopy(self.source)
        del changed[PROXY_MENU][PARENT + '/status']
        with self.assertRaises(AssertionError):
            self.assert_contract(self.overlay, changed)
        changed = copy.deepcopy(self.overlay)
        changed[TERMINAL_MENU][TERMINAL + '/config']['action']['path'] = 'wrong'
        with self.assertRaises(AssertionError):
            self.assert_contract(changed, self.source)

    def test_native_advanced_reboot_metadata_changes_are_rejected(self):
        name = 'luci-app-advanced-reboot.json'
        route = 'admin/system/advanced-reboot'
        for field, value in (('order', 92), ('action', {'type': 'view', 'path': 'wrong'}),
                             ('depends', {'acl': ['wrong']}), ('new-upstream-field', True)):
            with self.subTest(field=field):
                installed = copy.deepcopy(self.source)
                installed[name][route][field] = value
                with self.assertRaises(AssertionError):
                    self.assert_contract(self.overlay, installed)
        overlay = copy.deepcopy(self.overlay)
        overlay[name] = copy.deepcopy(self.source[name])
        with self.assertRaises(AssertionError):
            self.assert_contract(overlay, self.source)

    def test_advanced_reboot_overlay_metadata_changes_are_rejected(self):
        name = 'luci-app-advanced-reboot.json'
        route = 'admin/system/advanced-reboot'
        for field, value in (('order', 90), ('action', {'type': 'view', 'path': 'wrong'}),
                             ('depends', {'acl': ['wrong']}), ('new-upstream-field', True)):
            with self.subTest(field=field):
                overlay = copy.deepcopy(self.overlay)
                overlay[name][route][field] = value
                with self.assertRaises(AssertionError):
                    self.assert_contract(overlay, self.source)

    def test_interposed_system_sibling_is_rejected(self):
        installed = copy.deepcopy(self.source)
        installed['interposed.json'] = {'admin/system/interposed': {
            'title': 'Interposed', 'order': 95}}
        with self.assertRaises(AssertionError):
            self.assert_contract(self.overlay, installed)

    def test_cpu_overlay_changes_only_order(self):
        name = 'luci-app-cpufreq.json'
        route = 'admin/system/cpufreq'
        for field, value in (('order', 90), ('action', {'type': 'view', 'path': 'wrong'}),
                             ('depends', {'acl': ['wrong']})):
            with self.subTest(field=field):
                overlay = copy.deepcopy(self.overlay)
                overlay[name][route][field] = value
                with self.assertRaises(AssertionError):
                    self.assert_contract(overlay, self.source)

    def test_interposed_actual_sibling_is_rejected(self):
        for order in (10, 10.5, 11):
            with self.subTest(order=order):
                changed = copy.deepcopy(self.source)
                changed['additional-service.json'] = {'admin/services/interposed': {
                    'title': 'Hzzz', 'order': order}}
                with self.assertRaises(AssertionError):
                    self.assert_contract(self.overlay, changed)

    @unittest.skipUnless(os.environ.get('MX_MENU_ROOT'), 'set MX_MENU_ROOT to an installed root')
    def test_actual_installed_root_contract(self):
        directory = Path(os.environ['MX_MENU_ROOT']) / 'usr/share/luci/menu.d'
        self.assertTrue(directory.is_dir())
        self.assert_contract(self.overlay, menu_files(directory))
        self.assertEqual(menu_files(directory)[TERMINAL_MENU], self.overlay[TERMINAL_MENU])
        self.assertEqual(menu_files(directory)['luci-app-advanced-reboot.json'],
                         self.overlay['luci-app-advanced-reboot.json'])
        self.assertEqual(menu_files(directory)['luci-app-cpufreq.json'],
                         self.overlay['luci-app-cpufreq.json'])


if __name__ == '__main__':
    unittest.main()
