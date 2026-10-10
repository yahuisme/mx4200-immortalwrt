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
                "ssid='ImmortalWrt'\nkey='password'\nencryption='none'\n",
            "package/base-files/files/bin/config_generate":
                "ipaddr='192.168.1.1'\n",
            "package/base-files/files/etc/openwrt_release":
                "DISTRIB_DESCRIPTION='%D %V %C'\nDISTRIB_RELEASE='%V'\n",
            "package/base-files/files/usr/lib/os-release":
                'PRETTY_NAME="%D %V"\nOPENWRT_RELEASE="%D %V %C"\n'
                'VERSION="%V"\nVERSION_ID="%v"\n',
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
            self.assertIn('PRETTY_NAME="%D %V"',
                          before["package/base-files/files/usr/lib/os-release"])
            version_before = Path(d, "include/version.mk").read_text()
            env = os.environ | {"WRT_IP": "192.168.10.1", "WRT_THEME": "aurora",
                                "WRT_SSID": "MX4200", "WRT_WORD": "12345678"}
            result = subprocess.run(["bash", str(ROOT / "Scripts/Settings.sh")],
                                    cwd=d, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            wifi = Path(d, "package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc").read_text()
            self.assertIn("encryption='psk2+ccmp'", wifi)
            self.assertIn("ssid='MX4200'", wifi)
            self.assertIn("key='12345678'", wifi)
            for relative, (old, new) in replacements.items():
                self.assertIn(old, before[relative], relative)
                self.assertEqual(Path(d, relative).read_text(),
                                 before[relative].replace(old, new).replace(
                                     'PRETTY_NAME="%D %V"', 'PRETTY_NAME="%D %C"'),
                                 relative)
            self.assertIn("192.168.10.1", Path(d,
                "package/base-files/files/bin/config_generate").read_text())
            self.assertEqual(Path(d, "include/version.mk").read_text(),
                             version_before.replace("ImmortalWRT", "ImmortalWrt"))
            after = {p.relative_to(d): p.read_bytes() for p in Path(d).rglob("*")
                     if p.is_file()}
            result = subprocess.run(["bash", str(ROOT / "Scripts/Settings.sh")],
                                    cwd=d, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(after, {p.relative_to(d): p.read_bytes()
                                    for p in Path(d).rglob("*") if p.is_file()})

    @unittest.skipUnless(os.environ.get('MX4200_PREPARED_SOURCE'),
                         'set MX4200_PREPARED_SOURCE for real version rendering')
    def test_prepared_version_rendering_uses_true_revision_and_date(self):
        source = Path(os.environ['MX4200_PREPARED_SOURCE'])
        revision = subprocess.check_output(['./scripts/getver.sh'], cwd=source, text=True).strip()
        epoch = subprocess.check_output(['./scripts/get_source_date_epoch.sh'],
                                        cwd=source, text=True).strip()
        self.assertRegex(revision, r'^r[0-9]+-[0-9a-f]{7,40}$')
        self.assertEqual(epoch, subprocess.check_output(
            ['git', 'log', '-1', '--format=%ct'], cwd=source, text=True).strip())
        self.assertTrue(subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip().startswith(
                revision.split('-', 1)[1]))
        # Execute the actual upstream VERSION_SED_SCRIPT, without any build targets.
        harness = '''empty:=
space:=$(empty) $(empty)
comma:=,
qstrip=$(strip $(subst ",,$(1)))
include .config
BOARD:=$(call qstrip,$(CONFIG_TARGET_BOARD))
SUBTARGET:=$(call qstrip,$(CONFIG_TARGET_SUBTARGET))
ARCH_PACKAGES:=$(call qstrip,$(CONFIG_TARGET_ARCH_PACKAGES))
REVISION:=$(shell ./scripts/getver.sh)
SOURCE_DATE_EPOCH:=$(shell ./scripts/get_source_date_epoch.sh)
SED:=sed -e
include include/version.mk
.PHONY: render
render:
\t@$(VERSION_SED_SCRIPT) $(TEMPLATE)
'''
        rendered = {}
        with tempfile.TemporaryDirectory() as d:
            makefile = Path(d, 'version.mk')
            makefile.write_text(harness)
            for name in ('etc/openwrt_release', 'usr/lib/os-release', 'etc/banner'):
                rendered[name] = subprocess.check_output(
                    ['make', '--no-print-directory', '-s', '-f', str(makefile), 'render',
                     'TEMPLATE=package/base-files/files/' + name], cwd=source, text=True)
        display = 'ImmortalWrt ' + revision
        self.assertIn("DISTRIB_DESCRIPTION='" + display + "'", rendered['etc/openwrt_release'])
        self.assertIn("DISTRIB_RELEASE='SNAPSHOT'", rendered['etc/openwrt_release'])
        self.assertIn('PRETTY_NAME="' + display + '"', rendered['usr/lib/os-release'])
        self.assertIn('OPENWRT_RELEASE="' + display + '"', rendered['usr/lib/os-release'])
        self.assertIn('BUILD_ID="' + revision + '"', rendered['usr/lib/os-release'])
        self.assertIn('OPENWRT_BUILD_DATE="' + epoch + '"', rendered['usr/lib/os-release'])
        self.assertIn('VERSION="SNAPSHOT"', rendered['usr/lib/os-release'])
        self.assertIn(' ' + display + '\n', rendered['etc/banner'])
        self.assertNotIn('CONFIG_VERSIONOPT=y', (source / '.config').read_text())

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