import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'Scripts/Settings.sh'


class VersionTest(unittest.TestCase):
    def test_settings_preserve_official_version_templates(self):
        # Minimal filesystem fixture exercises the entire settings script.
        files = {
            'feeds/luci/applications/luci-app-advanced-reboot/root/usr/share/luci/menu.d/luci-app-advanced-reboot.json': '{"order": 90}\n',
            'feeds/luci/collections/luci/Makefile': 'luci-theme-bootstrap\n',
            'feeds/luci/modules/luci-mod-system/flash.js': '192.168.1.1\n',
            'package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc':
                "ssid='OpenWrt'\nkey=''\nencryption='none'\n",
            'package/base-files/files/bin/config_generate': '192.168.1.1\n',
            'package/base-files/files/etc/openwrt_release': "DISTRIB_DESCRIPTION='%D %V %C'\n",
            'package/base-files/files/usr/lib/os-release': 'PRETTY_NAME="%D %V %C"\n',
            'package/base-files/files/etc/banner': ' %D %V, %C\n',
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            env = dict(os.environ, WRT_THEME='aurora', WRT_IP='192.168.10.1',
                       WRT_SSID='MX4200', WRT_WORD='12345678')
            subprocess.run(['bash', str(SCRIPT)], cwd=root, env=env,
                           check=True, capture_output=True)
            for name in files:
                if name.endswith(('openwrt_release', 'os-release', 'banner')):
                    self.assertEqual(files[name], (root / name).read_text(), name)


if __name__ == '__main__':
    unittest.main()
