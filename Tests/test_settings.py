"""Small regression checks for Settings.sh's required failure contract."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
DTS = 'target/linux/qualcommax/dts/ipq8174-mx4200v2.dts'
WIFI = '&wifi {\n\tstatus = "okay";\n\n\tqcom,ath11k-calibration-variant = "Linksys-MX4200v2";\n};\n'
MODE = '\tqcom,ath11k-fw-memory-mode = <1>;\n'


class SettingsScriptTests(unittest.TestCase):
    def test_complete_settings_hides_version_in_display_templates(self):
        # Set this to a pristine snapshot of real upstream files for integration
        # coverage; the default fixture keeps the same full-script contract.
        import shutil

        fixtures = {
            DTS: WIFI,
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
            dts_before = Path(d, DTS).read_bytes()
            platform_before = {p.relative_to(d): p.read_bytes()
                               for top in ('target', 'package/kernel')
                               for p in Path(d, top).rglob('*') if p.is_file()}
            platform_expected = dict(platform_before)
            platform_expected[Path(DTS)] = dts_before.replace(
                WIFI.encode(), WIFI.replace('};\n', MODE + '};\n').encode())
            before = {p: Path(d, p).read_text() for p in replacements}
            self.assertIn('PRETTY_NAME="%D %V"',
                          before["package/base-files/files/usr/lib/os-release"])
            version_before = Path(d, "include/version.mk").read_text()
            env = os.environ | {"WRT_IP": "192.168.10.1", "WRT_THEME": "aurora",
                                "WRT_SSID": "MX4200", "WRT_WORD": "12345678"}
            result = subprocess.run(["bash", str(ROOT / "Scripts/Settings.sh")],
                                    cwd=d, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(platform_expected, {p.relative_to(d): p.read_bytes()
                             for top in ('target', 'package/kernel')
                             for p in Path(d, top).rglob('*') if p.is_file()})
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

    def test_memory_mode_rejects_changed_templates_without_writing(self):
        # Run the exact embedded transformation, without unrelated settings.
        script = (ROOT / 'Scripts/Settings.sh').read_text().split("python3 - <<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        changed = WIFI.replace('};\n', MODE + '};\n')
        cases = [None, WIFI.replace('okay', 'disabled'), WIFI + WIFI,
                 changed.replace('<1>', '<0>'), changed.replace('<1>', '<2>'),
                 changed.replace(MODE, MODE + MODE),
                 WIFI + '&other {\n' + MODE + '};\n']
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as d:
                path = Path(d, DTS)
                path.parent.mkdir(parents=True)
                if content is not None:
                    path.write_text(content)
                result = subprocess.run(['python3', '-c', script], cwd=d, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_text() if path.exists() else None, content)

    @unittest.skipUnless(os.environ.get('SETTINGS_PRISTINE_SOURCE'),
                         'set SETTINGS_PRISTINE_SOURCE for real DTS boundary checks')
    def test_real_memory_mode_changes_only_one_v2_line(self):
        import shutil
        source = Path(os.environ['SETTINGS_PRISTINE_SOURCE'])
        script = (ROOT / 'Scripts/Settings.sh').read_text().split("python3 - <<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(source, d, dirs_exist_ok=True)
            before = {p.relative_to(d): p.read_bytes() for p in Path(d).rglob('*') if p.is_file()}
            for protected in (
                'target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8074-512m.dtsi',
                'target/linux/qualcommax/patches-6.18/0102-arm64-dts-ipq8074-add-reserved-memory-nodes.patch',
                'package/kernel/mac80211/patches/ath11k/903-ath11k-support-setting-FW-memory-mode-via-DT.patch',
            ):
                self.assertIn(Path(protected), before)
            self.assertIn(MODE.encode(), before[Path(DTS.replace('v2.dts', 'v1.dts'))])
            self.assertNotIn(MODE.encode(), before[Path(DTS)])
            expected = dict(before)
            expected[Path(DTS)] = before[Path(DTS)].replace(
                WIFI.encode(), WIFI.replace('};\n', MODE + '};\n').encode())
            self.assertNotEqual(expected, before)
            for _ in range(2):
                subprocess.run(['python3', '-c', script], cwd=d, check=True)
                self.assertEqual(expected, {p.relative_to(d): p.read_bytes()
                                           for p in Path(d).rglob('*') if p.is_file()})

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