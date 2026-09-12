"""Execute Settings against pinned LuCI menu definitions, without network access.

Source: immortalwrt/immortalwrt v25.12.2, commit
4fc16f2985a358bd43bb522e43f05395fcbd6ed5, feeds.conf.default pins
immortalwrt/luci d6167ea0645cbd1327708d85f94824f42d0eb872.
The app definitions below are complete; the core excerpt keeps flash/reboot.
Set LUCI_MENU_SOURCE to that feed checkout to exercise complete upstream files.
Its recursive Git tree has no luci-app-cpufreq Lua controller.
"""
import json
import os
from pathlib import Path
import unittest

from Tests import test_customization as customization

MENU_PATHS = {
    'cpufreq': 'applications/luci-app-cpufreq/root/usr/share/luci/menu.d/luci-app-cpufreq.json',
    'reboot': 'modules/luci-mod-system/root/usr/share/luci/menu.d/luci-mod-system.json',
    'advanced-reboot': 'applications/luci-app-advanced-reboot/root/usr/share/luci/menu.d/luci-app-advanced-reboot.json',
}
MENUS = {
    'cpufreq': {
        'admin/system/cpufreq': {
            'title': 'CPU Freq', 'order': 90,
            'action': {'type': 'view', 'path': 'cpufreq'},
            'depends': {'acl': ['luci-app-cpufreq'], 'uci': {'cpufreq': True}},
        },
    },
    'reboot': {
        'admin/system/flash': {
            'title': 'Backup / Flash Firmware', 'order': 70,
            'action': {'type': 'view', 'path': 'system/flash'},
            'depends': {'acl': ['luci-mod-system-flash']},
        },
        'admin/system/reboot': {
            'title': 'Reboot', 'order': 90,
            'action': {'type': 'view', 'path': 'system/reboot'},
            'depends': {'acl': ['luci-mod-system-reboot']},
        },
    },
    'advanced-reboot': {
        'admin/system/advanced-reboot': {
            'title': 'Advanced Reboot', 'order': 90,
            'action': {'type': 'view', 'path': 'system/advanced-reboot'},
            'depends': {'acl': ['luci-app-advanced-reboot']},
        },
    },
}


def install_menu_fixture(root):
    for name, relative in MENU_PATHS.items():
        path = root / 'feeds/luci' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        source = os.environ.get('LUCI_MENU_SOURCE')
        path.write_bytes((Path(source) / relative).read_bytes() if source else
                         (json.dumps(MENUS[name], indent='\t') + '\n').encode())


class MenuOrderTests(customization.SettingsTests):
    def setUp(self):
        customization.SettingsTests.setUp(self)
        install_menu_fixture(self.root)
        self.paths = {name: self.root / 'feeds/luci' / path for name, path in MENU_PATHS.items()}

    def test_order_metadata_exact_writes_and_idempotence(self):
        # Apply existing hooks first, then restore menus to isolate their writes.
        result = self.run_settings(customization.VALUES)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Restore only upstream menus to isolate this change from existing hooks.
        install_menu_fixture(self.root)
        before = self.snapshot()
        originals = {name: json.loads(path.read_text()) for name, path in self.paths.items()}
        result = self.run_settings(customization.VALUES)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self.snapshot()
        self.assertEqual(set(before), set(after), 'No menu overlays or other new files')
        changed = {name for name in before if before[name][0] != after[name][0]}
        self.assertEqual(changed, {str(self.paths[name].relative_to(self.root))
                                  for name in ('cpufreq', 'advanced-reboot')})
        orders = {}
        for name, path in self.paths.items():
            actual = json.loads(path.read_text())
            key = 'admin/system/' + name
            orders[name] = actual[key]['order']
            actual[key]['order'] = originals[name][key]['order']
            self.assertEqual(actual, originals[name], 'Only order may change')
        self.assertEqual(orders, {'cpufreq': 89, 'reboot': 90, 'advanced-reboot': 91})
        self.assertEqual(sorted(orders, key=orders.get), ['cpufreq', 'reboot', 'advanced-reboot'])
        result = self.run_settings(customization.VALUES)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({k: v[0] for k, v in self.snapshot().items()},
                         {k: v[0] for k, v in after.items()})
        for path in self.paths.values():
            key = str(path.relative_to(self.root))
            self.assertEqual(self.snapshot()[key], after[key], 'Unchanged menus must not be rewritten')

    def test_required_files_fail_before_any_writes(self):
        for name, path in self.paths.items():
            with self.subTest(name=name):
                original = path.read_bytes()
                path.unlink()
                before = self.snapshot()
                result = self.run_settings(customization.VALUES)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.snapshot(), before)
                self.assertIn(path.name, result.stderr)
                path.write_bytes(original)

    def test_invalid_required_entries_fail_before_any_writes(self):
        for name, path in self.paths.items():
            original = path.read_bytes()
            for broken in ('{}', '{', json.dumps({'admin/system/' + name: {'order': '90'}})):
                with self.subTest(name=name, broken=broken):
                    path.write_text(broken)
                    before = self.snapshot()
                    result = self.run_settings(customization.VALUES)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.snapshot(), before)
                    self.assertIn(path.name, result.stderr)
            path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
