"""Regression checks for settings and official stable version rendering.

SETTINGS_PRISTINE_SOURCE supplies pristine stable files plus LuCI.
MX4200_PREPARED_SOURCE supplies a tagged stable Git tree with version/version.date
and .config; the render harness runs no build targets or compilation.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
DTS = 'target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-mx4200v2.dts'
WIFI = '&wifi {\n\tstatus = "okay";\n\n\tqcom,ath11k-calibration-variant = "Linksys-MX4200v2";\n};\n'


class SettingsScriptTests(unittest.TestCase):
    def test_complete_settings_preserves_stable_version_templates(self):
        # Set SETTINGS_PRISTINE_SOURCE to pristine real stable files for integration
        # coverage; the default fixture keeps the same full-script contract.
        import shutil

        fixtures = {
            DTS: WIFI,
            DTS.replace('v2.dts', 'v1.dts'): '#include "ipq8074-512m.dtsi"\n',
            "feeds/luci/collections/luci/Makefile":
                "DEPENDS:= +luci-base +luci-theme-bootstrap +luci-mod-admin-full\n# attendedsysupgrade\n",
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
        version_files = (
            "package/base-files/files/etc/openwrt_release",
            "package/base-files/files/usr/lib/os-release",
            "package/base-files/files/etc/banner",
        )
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
            platform_expected[Path(DTS.replace('v2.dts', 'v1.dts'))] = platform_before[Path(DTS.replace('v2.dts', 'v1.dts'))]
            platform_expected[Path(DTS)] = dts_before
            before = {p: Path(d, p).read_text() for p in (
                "package/base-files/files/etc/openwrt_release",
                "package/base-files/files/usr/lib/os-release",
                "package/base-files/files/etc/banner",
            )}
            self.assertIn('PRETTY_NAME="%D %V"',
                          before["package/base-files/files/usr/lib/os-release"])
            version_before = Path(d, "include/version.mk").read_text()
            env = os.environ | {"WRT_IP": "192.168.10.1", "WRT_THEME": "aurora",
                                "WRT_SSID": "MX4200", "WRT_WORD": "12345678"}
            result = subprocess.run(["bash", str(ROOT / "scripts/settings.sh")],
                                    cwd=d, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            collection = Path(d, "feeds/luci/collections/luci/Makefile").read_text()
            self.assertNotIn("luci-theme-bootstrap", collection)
            self.assertNotIn("luci-theme-aurora", collection)
            self.assertIn("+luci-base", collection)
            self.assertIn("+luci-mod-admin-full", collection)
            self.assertEqual(platform_expected, {p.relative_to(d): p.read_bytes()
                             for top in ('target', 'package/kernel')
                             for p in Path(d, top).rglob('*') if p.is_file()})
            wifi = Path(d, "package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc").read_text()
            self.assertIn("encryption='psk2+ccmp'", wifi)
            self.assertIn("ssid='MX4200'", wifi)
            self.assertIn("key='12345678'", wifi)
            for relative in version_files:
                self.assertEqual(Path(d, relative).read_text(), before[relative], relative)
            self.assertIn("192.168.10.1", Path(d,
                "package/base-files/files/bin/config_generate").read_text())
            self.assertEqual(Path(d, "include/version.mk").read_text(),
                             version_before.replace("ImmortalWRT", "ImmortalWrt"))
            # Even if a cached source recipe remains, APK-owned templates must
            # not be edited; the first invocation above ran without this tree.
            cached_template = Path(d, 'package/luci-app-aurora-config/root/usr/share/aurora/default.template')
            cached_template.parent.mkdir(parents=True, exist_ok=True)
            cached_template.write_text("option nav_type 'mega-menu'\noption struct_radius_base '0.5rem'\n")
            after = {p.relative_to(d): p.read_bytes() for p in Path(d).rglob("*")
                     if p.is_file()}
            result = subprocess.run(["bash", str(ROOT / "scripts/settings.sh")],
                                    cwd=d, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(after, {p.relative_to(d): p.read_bytes()
                                    for p in Path(d).rglob("*") if p.is_file()})

    def test_settings_does_not_modify_official_memory_defaults(self):
        script = (ROOT / 'scripts/settings.sh').read_text()
        self.assertNotIn('qcom,ath11k-fw-memory-mode', script)
        self.assertNotIn('&q6_region', script)

    @unittest.skipUnless(os.environ.get('MX4200_PREPARED_SOURCE'),
                         'set MX4200_PREPARED_SOURCE for real version rendering')
    def test_prepared_version_rendering_uses_true_revision_and_date(self):
        source = Path(os.environ['MX4200_PREPARED_SOURCE'])
        revision = subprocess.check_output(['./scripts/getver.sh'], cwd=source, text=True).strip()
        epoch = subprocess.check_output(['./scripts/get_source_date_epoch.sh'],
                                        cwd=source, text=True).strip()
        self.assertRegex(revision, r'^r[0-9]+-[0-9a-f]{7,40}$')
        # Stable releases pin these files; their revision/date can predate tag HEAD.
        self.assertEqual(revision, (source / 'version').read_text().strip())
        self.assertEqual(epoch, (source / 'version.date').read_text().strip())
        self.assertRegex(epoch, r'^[0-9]+$')
        tag = subprocess.check_output(
            ['git', 'describe', '--tags', '--exact-match', 'HEAD'],
            cwd=source, text=True).strip()
        self.assertRegex(tag, r'^v[0-9]+\.[0-9]+\.[0-9]+$')
        stable = tag.removeprefix('v')
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
        display = 'ImmortalWrt ' + stable + ' ' + revision
        self.assertIn("DISTRIB_DESCRIPTION='" + display + "'", rendered['etc/openwrt_release'])
        self.assertIn("DISTRIB_RELEASE='" + stable + "'", rendered['etc/openwrt_release'])
        self.assertIn("DISTRIB_REVISION='" + revision + "'", rendered['etc/openwrt_release'])
        self.assertIn('PRETTY_NAME="ImmortalWrt ' + stable + '"', rendered['usr/lib/os-release'])
        self.assertIn('OPENWRT_RELEASE="' + display + '"', rendered['usr/lib/os-release'])
        self.assertIn('BUILD_ID="' + revision + '"', rendered['usr/lib/os-release'])
        self.assertIn('OPENWRT_BUILD_DATE="' + epoch + '"', rendered['usr/lib/os-release'])
        self.assertIn('VERSION="' + stable + '"', rendered['usr/lib/os-release'])
        self.assertIn('VERSION_ID="' + stable + '"', rendered['usr/lib/os-release'])
        self.assertIn(' ImmortalWrt ' + stable + ', ' + revision, rendered['etc/banner'])
        self.assertNotIn('CONFIG_VERSIONOPT=y', (source / '.config').read_text())

    def test_missing_fixture_fails(self):
        with tempfile.TemporaryDirectory() as d:
            for p in ("feeds/luci/collections", "feeds/luci/modules/luci-mod-system",
                      "package/network/config/wifi-scripts/files/lib/wifi"):
                Path(d, p).mkdir(parents=True)
            env = os.environ | {"WRT_IP": "192.168.1.1", "WRT_THEME": "aurora",
                                "WRT_SSID": "x", "WRT_WORD": "y"}
            r = subprocess.run(["bash", str(ROOT / "scripts/settings.sh")], cwd=d,
                               env=env, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("flash.js not found", r.stderr)


if __name__ == "__main__":
    unittest.main()