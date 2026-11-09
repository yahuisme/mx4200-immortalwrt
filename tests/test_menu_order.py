"""Source-grounded Services menu contract; no installed-image/trust claims.

The digest-locked fixture contains complete package-source menu files at exact
Git revisions, not firmware overlays. See installed_rootfs for opt-in single
or four-device extracted root checks, including all actual menu siblings.
Installed checks also require MX_MENU_RECORD=<matching build-record/build.json>;
the full recorded LuCI SHA selects a reviewed baseline, cross-checked against
the installed luci-base version. No expected bytes come from installed menus.
"""
import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from installed_rootfs import roots

ROOT = Path(__file__).resolve().parents[1]
MENUS = ROOT / 'user/default/files/usr/share/luci/menu.d'
STABLE_LUCI = 'd6167ea0645cbd1327708d85f94824f42d0eb872'
SNAPSHOT_LUCI = '319f7c96e3530246cf91cfdd9bacb3fa44dc3a4e'
BASELINES = {
    STABLE_LUCI: ('services-menu-contract.json',
                  '1265f37428e8d8c100d57322f5b8199d67f7e2f1855f6275183d11e19f462e40'),
    SNAPSHOT_LUCI: ('services-menu-snapshot-contract.json',
                    '2a59c315906ce42ab9c8ac9563e20dd514999e99107cc6d372eac60362d6599d'),
}
PARENT = 'admin/services/homeproxy'
TERMINAL = 'admin/services/ttyd'
PROXY_MENU = 'luci-app-homeproxy.json'
TERMINAL_MENU = 'luci-app-ttyd.json'


def menu_files(directory):
    return {p.name: json.loads(p.read_text()) for p in sorted(directory.glob('*.json'))}


def source_menus(revision):
    assert revision in BASELINES, f'Unreviewed LuCI revision: {revision!r}; refresh from exact source'
    filename, digest = BASELINES[revision]
    fixture = ROOT / 'tests/fixtures' / filename
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == digest, (
        'Refresh from exact package-source revisions, never the overlay or installed menus')
    data = json.loads(fixture.read_text())
    assert data['luci_revision'] == revision
    rows = dict(data['menus'])
    rows['luci-app-aurora.json'] = json.loads(
        (ROOT / 'tests/fixtures/aurora-menu-contract.json').read_text())
    source = {}
    for name, row in rows.items():
        assert re.fullmatch(r'[0-9a-f]{40}', row['revision'])
        if row['repository'] == 'https://github.com/immortalwrt/luci':
            assert row['revision'] == revision, f'Mixed LuCI source: {name}'
        assert hashlib.sha256(row['text'].encode()).hexdigest() == row['sha256']
        assert row['path'].endswith('/usr/share/luci/menu.d/' + name)
        source[name] = json.loads(row['text'])
    return source


def installed_source(root, record=None):
    if record is None:
        path = os.environ.get('MX_MENU_RECORD')
        assert path, 'set MX_MENU_RECORD to the matching build-record/build.json'
        record = json.loads(Path(path).read_text())
    luci = [row for row in record.get('feeds', []) if row.get('name') == 'feed/luci']
    assert len(luci) == 1, 'build record must identify exactly one feed/luci'
    assert luci[0].get('url') in ('https://github.com/immortalwrt/luci',
                                  'https://github.com/immortalwrt/luci.git'), 'Nonofficial LuCI source'
    revision = luci[0].get('sha')
    source = source_menus(revision)
    # Package identity is only a cross-check, never a source of expected menu bytes.
    packages = (root / 'lib/apk/db/installed').read_text().split('\n\n')
    versions = [line[2:] for block in packages if 'P:luci-base' in block.splitlines()
                for line in block.splitlines() if line.startswith('V:')]
    assert len(versions) == 1 and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+~' + revision[:7], versions[0]), (
        'installed luci-base revision does not match recorded LuCI revision')
    return source


class MenuOrderTests(unittest.TestCase):
    def setUp(self):
        self.source = source_menus(STABLE_LUCI)
        self.overlay = menu_files(MENUS)
        # Advanced Reboot's order is installed by its own package, not shared files/.
        self.overlay.update(menu_files(ROOT / 'user/default/menus'))

    def assert_contract(self, overlay, installed, device='mx4200v1', installed_root=False):
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
                self.assertIn(name, installed)
                self.assertEqual(installed[name], source, name)
        if device == 'homewrk':
            self.assertNotIn(reboot_menu, installed)
        else:
            self.assertIn(reboot_menu, installed)
            self.assertIn(installed[reboot_menu], (self.source[reboot_menu], overlay[reboot_menu]))
        self.assertIn(cpu_menu, installed)
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
        self.assertIn(TERMINAL_MENU, installed)
        if not installed_root:
            self.assertIn(installed[TERMINAL_MENU],
                          (self.source[TERMINAL_MENU], overlay[TERMINAL_MENU]))
        effective_overlay = {name: rows for name, rows in overlay.items()
                             if device != 'homewrk' or name != reboot_menu}
        # An extracted root must stand on its own: overlaying the recipe here
        # would conceal a missing/stale installed menu or incorrect order.
        menus = installed if installed_root else installed | effective_overlay
        if installed_root:
            for name, rows in effective_overlay.items():
                self.assertEqual(installed.get(name), rows, name)
        merged = {}
        for entries in menus.values():
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
        tail = [cpu_route, 'admin/system/reboot']
        if device != 'homewrk':
            tail.append(reboot_route)
        tail.append('admin/system/aurora')
        if device == 'homewrk':
            self.assertFalse(any('advanced-reboot' in path for path in merged))
        self.assertEqual(system[i:], tail)

    def test_stable_baseline_has_only_official_stable_routes(self):
        # Stable LuCI d6167ea has none of the three later snapshot routes.
        self.assertNotIn('admin/network/switch-vlan', self.source['luci-mod-network.json'])
        self.assertNotIn('admin/system/admin/pwpolicy', self.source['luci-mod-system.json'])
        self.assertNotIn('admin/system/plugins', self.source['luci-mod-system.json'])

    def test_exact_luci_revision_selects_complete_baseline(self):
        self.assertTrue(callable(globals().get('source_menus')),
                        'source-bound menu baseline selector is missing')
        stable = source_menus('d6167ea0645cbd1327708d85f94824f42d0eb872')
        snapshot = source_menus('319f7c96e3530246cf91cfdd9bacb3fa44dc3a4e')
        for name, route in (('luci-mod-network.json', 'admin/network/switch-vlan'),
                            ('luci-mod-system.json', 'admin/system/admin/pwpolicy'),
                            ('luci-mod-system.json', 'admin/system/plugins')):
            with self.subTest(route=route):
                self.assertNotIn(route, stable[name])
                self.assertIn(route, snapshot[name])
        for revision in ('stable', 'snapshot', 'd6167ea', 'D6167EA0645CBD1327708D85F94824F42D0EB872',
                         '0' * 40, None):
            with self.subTest(revision=revision), self.assertRaises(AssertionError):
                source_menus(revision)

    def test_installed_baseline_requires_matching_recorded_luci_source(self):
        self.assertTrue(callable(globals().get('installed_source')),
                        'installed source identity binding is missing')
        for revision in (STABLE_LUCI, SNAPSHOT_LUCI):
            record = {'feeds': [{'name': 'feed/luci',
                                 'url': 'https://github.com/immortalwrt/luci.git',
                                 'sha': revision}]}
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database = root / 'lib/apk/db/installed'
                database.parent.mkdir(parents=True)
                database.write_text('P:luci-base\nV:26.309.25350~' + revision[:7] + '\n\n')
                self.assertEqual(installed_source(root, record), source_menus(revision))
                record_path = root / 'build.json'
                record_path.write_text(json.dumps(record))
                with patch.dict(os.environ, {'MX_MENU_RECORD': str(record_path)}):
                    self.assertEqual(installed_source(root), source_menus(revision))
                with patch.dict(os.environ, {'MX_MENU_RECORD': ''}):
                    with self.assertRaisesRegex(AssertionError, 'MX_MENU_RECORD'):
                        installed_source(root)
                for invalid in ({'feeds': []}, {'feeds': record['feeds'] * 2},
                                {'feeds': [dict(record['feeds'][0], sha='0' * 40)]},
                                {'feeds': [dict(record['feeds'][0], sha=revision[:7])]},
                                {'feeds': [dict(record['feeds'][0], url='https://example.org/luci.git')]}):
                    with self.subTest(revision=revision, record=invalid), self.assertRaises(AssertionError):
                        installed_source(root, invalid)
                database.write_text('P:luci-base\nV:26.309.25350~0000000\n\n')
                with self.assertRaisesRegex(AssertionError, 'luci-base.*revision'):
                    installed_source(root, record)
                database.write_text('P:other\nV:1\n\n')
                with self.assertRaisesRegex(AssertionError, 'luci-base'):
                    installed_source(root, record)

    def test_stable_and_snapshot_contracts_keep_all_source_checks(self):
        stable = source_menus(STABLE_LUCI)
        snapshot = source_menus(SNAPSHOT_LUCI)
        for revision, baseline in ((STABLE_LUCI, stable), (SNAPSHOT_LUCI, snapshot)):
            with self.subTest(revision=revision):
                self.source = baseline
                self.assert_contract(self.overlay, baseline)
                self.assertEqual(baseline[PROXY_MENU], stable[PROXY_MENU])
                # Complete-object equality retains order/action/ACL/UCI metadata
                # in both lanes, not just presence/absence of the three routes.
                for field, value in (('order', -1), ('action', {'type': 'firstchild'}),
                                     ('depends', {'acl': ['wrong']}),
                                     ('depends', {'uci': {'wireless': False}})):
                    changed = copy.deepcopy(baseline)
                    changed['luci-mod-network.json']['admin/network/wireless'][field] = value
                    with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                        self.assert_contract(self.overlay, changed)
                other = snapshot if revision == STABLE_LUCI else stable
                for name in ('luci-mod-network.json', 'luci-mod-system.json'):
                    changed = copy.deepcopy(baseline)
                    changed[name] = other[name]
                    with self.subTest(cross_lane=name), self.assertRaises(AssertionError):
                        self.assert_contract(self.overlay, changed)

    def test_complete_source_menus_and_actual_sibling_adjacency(self):
        expected = {'luci-app-homeproxy.json', 'luci-app-ttyd.json', 'luci-app-wol.json',
                    'luci-app-advanced-reboot.json', 'luci-app-firewall.json',
                    'luci-app-package-manager.json', 'luci-base.json',
                    'luci-mod-network.json', 'luci-mod-status.json', 'luci-mod-system.json',
                    'luci-app-aurora.json', 'luci-app-cpufreq.json'}
        self.assertEqual(set(self.source), expected)
        recipe = (ROOT / 'user/default/config.diff').read_text()
        for package in ('homeproxy', 'ttyd', 'wol', 'advanced-reboot', 'cpufreq'):
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

    def test_homewrk_source_contract_has_three_entry_tail(self):
        installed = copy.deepcopy(self.source)
        del installed['luci-app-advanced-reboot.json']
        self.assert_contract(self.overlay, installed, device='homewrk')

    def test_actual_installed_root_contract(self):
        selected = roots()
        if not selected:
            self.skipTest('set MX_ROOTFS_BASE or MX_MENU_ROOT + MX_MENU_DEVICE')
        for device, root in selected:
            with self.subTest(device=device):
                self.source = installed_source(root)
                directory = root / 'usr/share/luci/menu.d'
                self.assertTrue(directory.is_dir())
                self.assert_contract(self.overlay, menu_files(directory), device, installed_root=True)
                database = (root / 'lib/apk/db/installed').read_text()
                for name in ('luci-app-cpufreq', 'luci-i18n-cpufreq-zh-cn'):
                    self.assertIn('P:' + name + '\n', database)
                for name in ('www/luci-static/resources/view/cpufreq.js',
                             'usr/share/rpcd/acl.d/luci-app-cpufreq.json',
                             'usr/lib/lua/luci/i18n/cpufreq.zh-cn.lmo'):
                    path = root / name
                    self.assertTrue(path.is_file() and path.stat().st_size, name)

    def test_actual_installed_menu_mutations_are_rejected(self):
        selected = roots()
        if not selected:
            self.skipTest('set MX_ROOTFS_BASE or MX_MENU_ROOT + MX_MENU_DEVICE')
        for device, root in selected:
            self.source = installed_source(root)
            installed = menu_files(root / 'usr/share/luci/menu.d')
            # Prove the positive before negatives, so a wrong baseline cannot
            # make every mutation trivially "pass" by rejecting the original.
            self.assert_contract(self.overlay, installed, device, installed_root=True)
            mutations = []
            changed = copy.deepcopy(installed)
            # A valid upstream order must still fail for a final root; recipe
            # overlays must not be applied in-memory to hide a stale install.
            changed['luci-app-cpufreq.json']['admin/system/cpufreq']['order'] = 90
            mutations.append(('stale-cpu-order', changed))
            changed = copy.deepcopy(installed)
            del changed[TERMINAL_MENU]
            mutations.append(('missing-terminal', changed))
            changed = copy.deepcopy(installed)
            if device == 'homewrk':
                changed['renamed.json'] = copy.deepcopy(self.source['luci-app-advanced-reboot.json'])
            else:
                del changed['luci-app-advanced-reboot.json']
            mutations.append(('wrong-device-advanced-reboot', changed))
            changed = copy.deepcopy(installed)
            changed['between.json'] = {'admin/system/between': {'title': 'Between', 'order': 95}}
            mutations.append(('interposed-system-sibling', changed))
            for mutation, changed in mutations:
                with self.subTest(device=device, mutation=mutation):
                    with self.assertRaises(AssertionError):
                        self.assert_contract(self.overlay, changed, device, installed_root=True)


if __name__ == '__main__':
    unittest.main()
