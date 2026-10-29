"""Keep the proxy entry immediately before the terminal menu."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MENUS = ROOT / 'user/default/files/usr/share/luci/menu.d'


class MenuOrderTests(unittest.TestCase):
    def test_nikki_precedes_terminal_without_losing_routes(self):
        nikki = json.loads((MENUS / 'luci-app-nikki.json').read_text())
        terminal = json.loads((MENUS / 'luci-app-ttyd.json').read_text())
        entry = nikki['admin/services/nikki']
        self.assertEqual(entry['order'], terminal['admin/services/ttyd']['order'] - 1)
        self.assertEqual(entry['title'], 'Nikki')
        self.assertEqual(entry['action'], {'type': 'firstchild'})
        self.assertEqual(entry['depends'], {
            'acl': ['luci-app-nikki'], 'uci': {'nikki': True}})
        routes = {'config': 'app', 'profile': 'profile', 'mixin': 'mixin',
                  'proxy': 'proxy', 'editor': 'editor', 'log': 'log'}
        self.assertEqual(set(nikki), {'admin/services/nikki'} | {
            'admin/services/nikki/' + name for name in routes})
        for name, view in routes.items():
            self.assertEqual(nikki['admin/services/nikki/' + name]['action'],
                             {'type': 'view', 'path': 'nikki/' + view})


if __name__ == '__main__':
    unittest.main()
