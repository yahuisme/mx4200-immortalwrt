"""Execute customization hooks against disposable buildroots, never the live tree."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VALUES = dict(WRT_THEME="aurora", WRT_IP="192.168.8.1", WRT_SSID="MX4200", WRT_WORD="test-password")
WIFI_PATH = "package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc"
REBOOT_MENU = "feeds/luci/applications/luci-app-advanced-reboot/root/usr/share/luci/menu.d/luci-app-advanced-reboot.json"
# Official wifi-scripts uses an encryption variable, not a literal UCI default.
WIFI_TEMPLATE = """\
        let country, encryption, defaults, num_global_macaddr;
        if (band_name == '6g') {
            country = '00';
            encryption = 'owe';
        } else {
            encryption = 'none';
        }
        print(`set ${si}=wifi-iface
set ${si}.device='${name}'
set ${si}.network='lan'
set ${si}.mode='ap'
set ${si}.ssid='${defaults?.ssid || "ImmortalWrt"}'
set ${si}.encryption='${defaults?.encryption || encryption}'
set ${si}.key='${defaults?.key || ""}'
set ${si}.disabled='0'

`);
"""


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = {
            REBOOT_MENU: '{"order": 90}\n',
            "feeds/luci/collections/luci/Makefile": "DEPENDS:=+luci-theme-bootstrap\n +luci-app-attendedsysupgrade\n",
            "feeds/luci/modules/luci-mod-system/htdocs/flash.js": "const ip = '192.168.1.1';\n",
            WIFI_PATH: WIFI_TEMPLATE,
            "package/base-files/files/bin/config_generate": "ip=192.168.1.1\nhostname=ImmortalWRT\n",
            "package/base-files/files/etc/openwrt_release": "%D %V %C\n",
            "package/base-files/files/usr/lib/os-release": "%D %V %C\n",
            "package/base-files/files/etc/banner": "%D %V, %C\n",
            "include/version.mk": "VERSION_DIST:=ImmortalWRT\n",
        }
        for name, text in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def run_settings(self, values):
        env = {k: v for k, v in os.environ.items() if k not in VALUES}
        env.update(values)
        return subprocess.run(["bash", str(ROOT / "Scripts/Settings.sh")], cwd=self.root,
                              env=env, capture_output=True, text=True)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino)
                for p in self.root.rglob("*") if p.is_file()}

    def test_missing_or_empty_variables_make_no_writes(self):
        for variable in VALUES:
            for empty in (False, True):
                with self.subTest(variable=variable, empty=empty):
                    values = VALUES.copy()
                    if empty:
                        values[variable] = ""
                    else:
                        values.pop(variable)
                    before = self.snapshot()
                    result = self.run_settings(values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.snapshot(), before)
                    self.assertIn(variable, result.stderr)

    def test_wifi_template_requires_wpa2_ccmp_with_the_configured_key(self):
        result = self.run_settings(VALUES)
        self.assertEqual(result.returncode, 0, result.stderr)
        wifi = (self.root / WIFI_PATH).read_text()
        self.assertIn("set ${si}.encryption='psk2+ccmp'\n", wifi)
        self.assertIn("set ${si}.ssid='MX4200'\n", wifi)
        self.assertIn("set ${si}.key='test-password'\n", wifi)
        self.assertNotIn("set ${si}.encryption='${", wifi)

    def test_normal_settings_preserve_all_customizations(self):
        result = self.run_settings(VALUES)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {
            **self.files,
            REBOOT_MENU: '{"order": 91}\n',
            "feeds/luci/collections/luci/Makefile": "DEPENDS:=+luci-theme-aurora\n",
            "feeds/luci/modules/luci-mod-system/htdocs/flash.js": "const ip = '192.168.8.1';\n",
            WIFI_PATH: WIFI_TEMPLATE.replace(
                "ssid='${defaults?.ssid || \"ImmortalWrt\"}'", "ssid='MX4200'"
            ).replace(
                "encryption='${defaults?.encryption || encryption}'", "encryption='psk2+ccmp'"
            ).replace("key='${defaults?.key || \"\"}'", "key='test-password'"),
            "package/base-files/files/bin/config_generate": "ip=192.168.8.1\nhostname=ImmortalWrt\n",
            "include/version.mk": "VERSION_DIST:=ImmortalWrt\n",
        }
        for name, text in expected.items():
            self.assertEqual((self.root / name).read_text(), text, name)

    def test_optional_version_file(self):
        (self.root / "include/version.mk").unlink()
        result = self.run_settings(VALUES)
        self.assertEqual(result.returncode, 0, result.stderr)


class PackagesTests(unittest.TestCase):
    def test_replacements_remove_live_and_dangling_feed_links(self):
        # Real git repositories/clones, redirected locally: no network or mocks.
        import json
        for dangling in (False, True):
            with self.subTest(dangling=dangling), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "buildroot"
                package = root / "package"
                package.mkdir(parents=True)
                (root / "rules.mk").touch()
                (root / "source-lock.json").write_text('{"official": "preserved"}\n')
                for name in ("qca-nss-drv", "qca-nss-ecm", "qca-nss-clients", "nss-firmware"):
                    path = package / "qca-nss" / name
                    path.mkdir(parents=True)
                    (path / "Makefile").touch()
                links = []
                sources = []
                for feed, subdir, name in (("luci", "applications", "luci-app-homeproxy"),
                                           ("packages", "net", "sing-box")):
                    source = root / "feeds" / feed / subdir / name
                    source.parent.mkdir(parents=True)
                    if not dangling:
                        source.mkdir()
                        (source / "Makefile").write_text("official package\n")
                    link = package / "feeds" / feed / name
                    link.parent.mkdir(parents=True)
                    link.symlink_to(f"../../../feeds/{feed}/{subdir}/{name}")
                    links.append(link)
                    sources.append(source)
                untouched = root / "feeds/packages/net/other"
                untouched.mkdir()
                (untouched / "Makefile").write_text("keep me\n")
                other_link = package / "feeds/packages/other"
                other_link.symlink_to("../../../feeds/packages/net/other")
                env = os.environ.copy()
                for key in list(env):
                    if key.startswith("GIT_CONFIG_"):
                        env.pop(key)
                env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_COUNT="0")
                urls = (
                    ("https://github.com/eamonxg/luci-theme-aurora.git", ("luci-theme-aurora",)),
                    ("https://github.com/eamonxg/luci-app-aurora-config.git", ("luci-app-aurora-config",)),
                    ("https://github.com/VIKINGYFY/packages.git", ("luci-app-homeproxy", "sing-box")),
                )
                # Package-owned resources must survive byte-for-byte; no CDN refresh.
                resources = {
                    "geoip_cn.srs": b"SRS\x01fixture-geoip",
                    "geoip_cn.ver": b"20260812\n",
                    "geosite_cn.srs": b"SRS\x01fixture-geosite",
                    "geosite_cn.ver": b"20260908094002\n",
                }
                tools = Path(tmp) / "bin"
                tools.mkdir()
                curl = tools / "curl"
                curl.write_text("#!/bin/sh\necho 'Unexpected resource download' >&2\nexit 99\n")
                curl.chmod(0o755)
                env["PATH"] = str(tools) + os.pathsep + env["PATH"]
                commits = []
                for i, (url, names) in enumerate(urls):
                    repo = Path(tmp) / f"remote-{i}"
                    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
                    for name in names:
                        path = repo / name if i == 2 else repo
                        path.mkdir(exist_ok=True)
                        (path / "Makefile").write_text(f"custom {name}\n")
                        if name == "luci-app-homeproxy":
                            bundled = path / "root/etc/homeproxy/resources"
                            bundled.mkdir(parents=True)
                            for filename, content in resources.items():
                                (bundled / filename).write_bytes(content)
                    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
                    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture",
                                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"],
                                   check=True, env=env)
                    commits.append(subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                                           text=True, env=env).strip())
                    env[f"GIT_CONFIG_KEY_{i}"] = f"url.{repo.as_uri()}.insteadOf"
                    env[f"GIT_CONFIG_VALUE_{i}"] = url
                    env["GIT_CONFIG_COUNT"] = str(i + 1)
                result = subprocess.run(["bash", str(ROOT / "Scripts/Packages.sh")], cwd=package,
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                for link, source in zip(links, sources):
                    self.assertFalse(link.is_symlink(), f"stale install link: {link}")
                    self.assertFalse(link.exists())
                    self.assertFalse(source.exists())
                for _, names in urls:
                    for name in names:
                        self.assertEqual((package / name / "Makefile").read_text(), f"custom {name}\n")
                homeproxy = package / "luci-app-homeproxy/root/etc/homeproxy"
                for filename, content in resources.items():
                    self.assertEqual((homeproxy / "resources" / filename).read_bytes(), content)
                self.assertFalse((homeproxy / "dashboard").exists())
                self.assertTrue(other_link.is_symlink())
                self.assertEqual((other_link / "Makefile").read_text(), "keep me\n")
                lock = json.loads((root / "source-lock.json").read_text())
                self.assertEqual(lock["official"], "preserved")
                self.assertEqual(len(lock["firmware_inputs_sha256"]), 64)
                self.assertEqual(set(lock["custom_package_sha256"]), {"aurora", "aurora-config", "VIKINGYFY/packages"})
                self.assertEqual(lock["custom_packages"], dict(zip(
                    ("aurora", "aurora-config", "VIKINGYFY/packages"), commits)))


if __name__ == "__main__":
    unittest.main()
