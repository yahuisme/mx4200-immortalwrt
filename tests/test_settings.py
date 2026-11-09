"""Regression checks for settings and official stable version rendering.

SETTINGS_PRISTINE_SOURCE supplies pristine stable files plus pinned LuCI.
MX_VERSION_SOURCE supplies a stable Git tree and requested .config for version
rendering only; MX4200_PREPARED_SOURCE remains a final defconfig/package fixture.
The render harness runs no firmware build targets or compilation.
"""
import os
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
DTS = 'target/linux/qualcommax/dts/ipq8174-mx4200v2.dts'
WIFI = '&wifi {\n\tstatus = "okay";\n\n\tqcom,ath11k-calibration-variant = "Linksys-MX4200v2";\n};\n'


class SettingsScriptTests(unittest.TestCase):
    def run_wireless_settings(self, wireless):
        with tempfile.TemporaryDirectory() as d:
            fixtures = {
                'feeds/luci/applications/luci-app-advanced-reboot/root/usr/share/luci/menu.d/luci-app-advanced-reboot.json': '{}',
                'feeds/luci/collections/luci/Makefile': 'LUCI_DEPENDS:=+luci-light\n',
                'feeds/luci/modules/luci-mod-system/htdocs/flash.js': "const ip = '192.168.1.1';\n",
                'package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc': wireless,
                'package/base-files/files/bin/config_generate': "ipaddr='192.168.1.1'\n",
            }
            for relative, text in fixtures.items():
                path = Path(d, relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            env = os.environ | {'WRT_IP': '192.168.10.1', 'WRT_SSID': 'MX4200',
                                'WRT_WORD': '12345678'}
            result = subprocess.run(['bash', str(ROOT / 'scripts/settings.sh')],
                                    cwd=d, env=env, capture_output=True, text=True)
            return result, Path(d, 'package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc').read_text()

    def assert_wireless_zero_match_rejected(self, option, requested):
        defaults = {'ssid': 'ImmortalWrt', 'key': 'password', 'encryption': 'none'}
        wireless = ''.join(f"set ${{si}}.{name}='{value}'\n"
                           for name, value in defaults.items() if name != option)
        for comment in ('', f"// set ${{si}}.{option}='{requested}'\n"):
            with self.subTest(option=option, misleading_comment=bool(comment)):
                result, _ = self.run_wireless_settings(wireless + comment)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f'failed to set default wireless {option}', result.stderr)
                self.assertNotIn('wifi default ssid/key has been set!', result.stdout)

    def test_wireless_ssid_zero_match_rejected(self):
        self.assert_wireless_zero_match_rejected('ssid', 'MX4200')

    def test_wireless_key_zero_match_rejected(self):
        self.assert_wireless_zero_match_rejected('key', '12345678')

    def test_wireless_encryption_zero_match_rejected(self):
        self.assert_wireless_zero_match_rejected('encryption', 'psk2+ccmp')

    def test_complete_settings_preserves_official_version_templates(self):
        # Set SETTINGS_PRISTINE_SOURCE to pristine real stable files for integration
        # coverage; the default fixture keeps the same full-script contract.
        import shutil

        menu_path = 'feeds/luci/applications/luci-app-advanced-reboot/root/usr/share/luci/menu.d/luci-app-advanced-reboot.json'
        source_menu = json.loads((ROOT / 'tests/fixtures/services-menu-contract.json').read_text())['menus']['luci-app-advanced-reboot.json']['text']
        fixtures = {
            menu_path: source_menu,
            DTS: WIFI,
            DTS.replace('v2.dts', 'v1.dts'): '#include "ipq8074-512m.dtsi"\n',
            "feeds/luci/collections/luci/Makefile":
                "LUCI_DEPENDS:=+luci-light +luci-app-package-manager\n# attendedsysupgrade\n",
            "feeds/luci/collections/luci-light/Makefile":
                "LUCI_DEPENDS:=+luci-mod-admin-full +luci-theme-bootstrap\n",
            "feeds/luci/modules/luci-mod-admin-full/Makefile":
                "LUCI_DEPENDS:=+luci-base +luci-mod-status +luci-mod-system +luci-mod-network\n",
            "feeds/luci/modules/luci-mod-system/htdocs/flash.js":
                "const ip = '192.168.1.1';\n",
            "package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc":
                "set ${si}.ssid='ImmortalWrt'\nset ${si}.key='password'\nset ${si}.encryption='none'\n",
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
            upstream = os.environ.get("SETTINGS_PRISTINE_SOURCE", str(ROOT / "tests/fixtures/snapshot-source"))
            if upstream:
                shutil.copytree(upstream, d, dirs_exist_ok=True)
            else:
                for relative, text in fixtures.items():
                    path = Path(d, relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
            candidates = (DTS, 'target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-mx4200v2.dts')
            matches = [name for name in candidates if Path(d, name).is_file()]
            self.assertEqual(len(matches), 1, 'missing or ambiguous MX4200v2 DTS')
            dts = matches[0]
            dts_before = Path(d, dts).read_bytes()
            platform_before = {p.relative_to(d): p.read_bytes()
                               for top in ('target', 'package/kernel')
                               for p in Path(d, top).rglob('*') if p.is_file()}
            platform_expected = dict(platform_before)
            platform_expected[Path(dts.replace('v2.dts', 'v1.dts'))] = platform_before[Path(dts.replace('v2.dts', 'v1.dts'))]
            platform_expected[Path(dts)] = dts_before
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
            self.assertEqual(Path(d, menu_path).read_bytes(),
                             (ROOT / 'user/default/menus/luci-app-advanced-reboot.json').read_bytes())
            graph = {}
            for makefile in Path(d, 'feeds/luci').glob('*/*/Makefile'):
                text = makefile.read_text().replace('\\\n', ' ')
                deps = re.findall(r'^LUCI_DEPENDS\s*[:+]?=\s*(.*)$', text, re.M)
                graph[makefile.parent.name] = {
                    token.removeprefix('+').split(':')[-1]
                    for line in deps for token in line.split()}
            # Follow the official collection graph rather than requiring flattened
            # direct dependencies in collections/luci/Makefile.
            self.assertIn('luci-light', graph['luci'])
            self.assertIn('luci-mod-admin-full', graph['luci-light'])
            closure, pending = set(), ['luci']
            while pending:
                package = pending.pop()
                if package not in closure:
                    closure.add(package)
                    pending.extend(graph.get(package, ()))
            self.assertTrue({'luci-base', 'luci-mod-admin-full', 'luci-mod-status',
                             'luci-mod-system', 'luci-mod-network'} <= closure)
            self.assertTrue({'luci-theme-bootstrap', 'luci-theme-aurora',
                             'luci-app-attendedsysupgrade'}.isdisjoint(closure))
            self.assertEqual(platform_expected, {p.relative_to(d): p.read_bytes()
                             for top in ('target', 'package/kernel')
                             for p in Path(d, top).rglob('*') if p.is_file()})
            wifi = Path(d, "package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc").read_text()
            self.assertIn("set ${si}.encryption='psk2+ccmp'", wifi.splitlines())
            self.assertIn("set ${si}.ssid='MX4200'", wifi.splitlines())
            self.assertIn("set ${si}.key='12345678'", wifi.splitlines())
            for relative in version_files:
                self.assertEqual(Path(d, relative).read_text(), before[relative], relative)
            self.assertIn("192.168.10.1", Path(d,
                "package/base-files/files/bin/config_generate").read_text())
            self.assertEqual(Path(d, "include/version.mk").read_text(),
                             version_before)
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

    @unittest.skipUnless(os.environ.get('MX_VERSION_SOURCE') or os.environ.get('MX4200_PREPARED_SOURCE'),
                         'set MX_VERSION_SOURCE for real version rendering')
    def test_prepared_version_rendering_uses_true_revision_and_date(self):
        source = Path(os.environ.get('MX_VERSION_SOURCE') or os.environ['MX4200_PREPARED_SOURCE'])
        revision = subprocess.check_output(['./scripts/getver.sh'], cwd=source, text=True).strip()
        epoch = subprocess.check_output(['./scripts/get_source_date_epoch.sh'],
                                        cwd=source, text=True).strip()
        self.assertRegex(revision, r'^r[0-9]+-[0-9a-f]{7,40}$')
        # Stable release metadata wins over tag HEAD SHA/commit date.
        self.assertEqual(revision, subprocess.check_output(
            ['git', 'show', 'HEAD:version'], cwd=source, text=True).strip())
        self.assertEqual(epoch, subprocess.check_output(
            ['git', 'show', 'HEAD:version.date'], cwd=source, text=True).strip())
        self.assertRegex(epoch, r'^[0-9]+$')
        candidates = (
            source / 'target/linux/qualcommax/files/arch/arm64/boot/dts/qcom',
            source / 'target/linux/qualcommax/dts',
        )
        for model, display in (('mx4200v1', 'Linksys MX4200v1'), ('mx4200v2', 'Linksys MX4200v2'),
                               ('mx4300', 'Linksys MX4300'), ('homewrk', 'Linksys HomeWRK')):
            dts_files = [directory / ('ipq8174-' + model + '.dts') for directory in candidates]
            matches = [path for path in dts_files if path.is_file()]
            self.assertEqual(len(matches), 1, model)
            self.assertIn('model = "' + display + '";', matches[0].read_text())
        version_text = (source / 'include/version.mk').read_text()
        match = re.search(r'^VERSION_NUMBER:=\$\(if \$\(VERSION_NUMBER\),\$\(VERSION_NUMBER\),([0-9]+\.[0-9]+\.[0-9]+)\)$', version_text, re.M)
        self.assertIsNotNone(match)
        assert match is not None
        version = match[1]
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
        display = 'ImmortalWrt ' + version + ' ' + revision
        self.assertIn("DISTRIB_DESCRIPTION='" + display + "'", rendered['etc/openwrt_release'])
        self.assertIn("DISTRIB_RELEASE='" + version + "'", rendered['etc/openwrt_release'])
        self.assertIn("DISTRIB_REVISION='" + revision + "'", rendered['etc/openwrt_release'])
        self.assertIn('PRETTY_NAME="ImmortalWrt ' + version + '"', rendered['usr/lib/os-release'])
        self.assertIn('OPENWRT_RELEASE="' + display + '"', rendered['usr/lib/os-release'])
        self.assertIn('BUILD_ID="' + revision + '"', rendered['usr/lib/os-release'])
        self.assertIn('OPENWRT_BUILD_DATE="' + epoch + '"', rendered['usr/lib/os-release'])
        self.assertIn('VERSION="' + version + '"', rendered['usr/lib/os-release'])
        self.assertIn('VERSION_ID="' + version + '"', rendered['usr/lib/os-release'])
        self.assertIn(' ImmortalWrt ' + version + ', ' + revision, rendered['etc/banner'])
        self.assertNotIn('CONFIG_VERSIONOPT=y', (source / '.config').read_text())
        # Exercise the pinned official overview renderer too, not just templates.
        # Board/LuCI RPC inputs are private fixtures; this is not router evidence.
        overview = source / ('feeds/luci/modules/luci-mod-status/htdocs/'
                             'luci-static/resources/view/status/include/10_system.js')
        if os.environ.get('SETTINGS_PRISTINE_SOURCE'):
            self.assertTrue(overview.is_file(), 'pinned LuCI overview source required')
            node = r'''
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
function E(tag, attrs, children) {
    return { tag, children: children || [], appendChild(row) { this.children.push(row); } };
}
// Execute only the exact pinned upstream JS; payload stays JSON, never code.
const component = new Function('baseclass', 'rpc', 'uci', 'L', '_', 'E',
    fs.readFileSync(process.argv[1], 'utf8'))(
    { extend: x => x }, { declare: () => () => {} }, { get: () => null },
    { isObject: x => x !== null && typeof x === 'object' }, x => x, E);
const rows = component.render([
    { hostname: 'fixture', model: payload.model, release: { description: payload.description } },
    {}, { cpubench: '' }, {}, {}, {},
    { branch: 'LuCI stable fixture', revision: 'git-fixture' }, 0
]).children;
console.log(JSON.stringify(Object.fromEntries(rows.map(row =>
    [row.children[0].children[0], row.children[1].children[0]]))));
'''
            for model in ('Linksys MX4200v1', 'Linksys MX4200v2', 'Linksys MX4300', 'Linksys HomeWRK'):
                result = subprocess.run(['node', '-e', node, str(overview)],
                                        input=json.dumps({'model': model, 'description': display}),
                                        text=True, capture_output=True, check=True)
                fields = json.loads(result.stdout)
                self.assertEqual(fields['Model'], model)
                self.assertEqual(fields['Firmware Version'],
                                 display + ' / LuCI stable fixture git-fixture')

    def test_missing_fixture_fails(self):
        with tempfile.TemporaryDirectory() as d:
            menu = Path(d, 'feeds/luci/applications/luci-app-advanced-reboot/root/usr/share/luci/menu.d/luci-app-advanced-reboot.json')
            menu.parent.mkdir(parents=True)
            menu.write_text('{}')
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
