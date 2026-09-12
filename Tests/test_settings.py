"""Small regression checks for Settings.sh's required failure contract."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class SettingsScriptTests(unittest.TestCase):
    def test_complete_settings_hides_version_in_display_templates(self):
        # Set this to a pristine snapshot of real upstream files for integration
        # coverage; the default fixture keeps the same full-script contract.
        import shutil

        fixtures = {
            "package/luci-app-aurora-config/root/usr/share/aurora/default.template":
                "option nav_type 'topbar'\noption struct_radius_base '1rem'\n",
            "feeds/luci/collections/luci/Makefile":
                "DEPENDS:=luci-theme-bootstrap\n# attendedsysupgrade\n",
            "feeds/luci/modules/luci-mod-system/htdocs/flash.js":
                "const ip = '192.168.1.1';\n",
            "package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc":
                "ssid='ImmortalWrt'\nkey='password'\n",
            "package/base-files/files/bin/config_generate":
                "ipaddr='192.168.1.1'\n",
            "package/base-files/files/etc/openwrt_release":
                "DISTRIB_DESCRIPTION='%D %V %C'\nDISTRIB_RELEASE='%V'\n",
            "package/base-files/files/usr/lib/os-release":
                'PRETTY_NAME="%D %V %C"\nVERSION="%V"\n',
            "package/base-files/files/etc/banner": "%D %V, %C\n",
            "include/version.mk": "VERSION_DIST:=ImmortalWRT\n",
        }
        replacements = {
            "package/base-files/files/etc/openwrt_release": ("%D %V %C", "%D %C"),
            "package/base-files/files/usr/lib/os-release": ("%D %V %C", "%D %C"),
            "package/base-files/files/etc/banner": ("%D %V, %C", "%D %C"),
        }
        with tempfile.TemporaryDirectory() as d:
            upstream = os.environ.get("SETTINGS_PRISTINE_SOURCE")
            if upstream:
                shutil.copytree(upstream, d, dirs_exist_ok=True)
            else:
                for relative, text in fixtures.items():
                    path = Path(d, relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
            before = {p: Path(d, p).read_text() for p in replacements}
            env = os.environ | {"WRT_IP": "192.168.10.1", "WRT_THEME": "aurora",
                                "WRT_SSID": "MX4200", "WRT_WORD": "12345678"}
            result = subprocess.run(["bash", str(ROOT / "Scripts/Settings.sh")],
                                    cwd=d, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for relative, (old, new) in replacements.items():
                self.assertIn(old, before[relative], relative)
                self.assertEqual(Path(d, relative).read_text(),
                                 before[relative].replace(old, new), relative)
            self.assertIn("192.168.10.1", Path(d,
                "package/base-files/files/bin/config_generate").read_text())
            self.assertNotIn("ImmortalWRT", Path(d, "include/version.mk").read_text())

    def test_missing_fixture_fails(self):
        with tempfile.TemporaryDirectory() as d:
            for p in ("package/luci-app-aurora-config/root/usr/share/aurora",
                      "feeds/luci/collections", "feeds/luci/modules/luci-mod-system",
                      "package/network/config/wifi-scripts/files/lib/wifi"):
                Path(d, p).mkdir(parents=True)
            env = os.environ | {"WRT_IP": "192.168.1.1", "WRT_THEME": "aurora",
                                "WRT_SSID": "x", "WRT_WORD": "y"}
            r = subprocess.run(["bash", str(ROOT / "Scripts/Settings.sh")], cwd=d,
                               env=env, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Aurora templates not found", r.stderr)


if __name__ == "__main__":
    unittest.main()