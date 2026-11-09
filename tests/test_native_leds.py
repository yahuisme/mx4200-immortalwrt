"""Ensure MX4200 does not install a custom LED preset or runtime owner."""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile
import unittest

from installed_rootfs import roots


REPO = Path(__file__).resolve().parents[1]
# Historical fallback: byte-for-byte official v25.12.2 source, commit below.
# Snapshot acceptance requires MX_OFFICIAL_SOURCE=<matching official checkout>.
# Hash Git objects, never customized worktree/output files; not extracted-image
# self-hashes or APK records (which a faulty overlay could leave unchanged).
# Source: https://github.com/immortalwrt/immortalwrt/tree/
# 4fc16f2985a358bd43bb522e43f05395fcbd6ed5
# All paths map to package/base-files/files/<path>, except 01_leds maps to
# target/linux/qualcommax/ipq807x/base-files/etc/board.d/01_leds.
NATIVE_LED_SHA256 = {
    'etc/board.d/01_leds': '3a928d67dc3738395da072bd1408bb80e7d1f4dab9a6d58bad5916220e400925',
    'etc/diag.sh': '6eb1bce44d815f2bacbb0d929421d53b883ee24650d684dc82a1a0462d6720ec',
    'etc/init.d/led': 'fad92d8c5cee73748034969acfb67ed9822683b840829cc6071185bd26863e3b',
    'lib/functions/leds.sh': '8afea8b5126e7dfdb00f6b56052061502973ba4bcb05e6dcc36b73948fcf3a7f',
    'lib/functions/uci-defaults.sh': '83b61f6e3c70c6e463640126f342ed4841c460a6a92b64d5b1163b41200c94d3',
    'sbin/led.sh': '285fdf8391d36d7dad1e2b008d3e71ab464ffe839fc830428cffa1677065f4d0',
}
LED_POLICY = re.compile(
    r'/sys/(?:class/leds|devices/[^\s]+/leds)|'
    r'\b(?:status_led\w*|led_set_attr|ucidef_set_led\w*)\b|'
    r'\bsystem\.(?:[^\s]+\.)?(?:led[\w-]*|@led\[)|'
    r'\bsystem\.[^\s=]+\s*=\s*[\'\"]?led\b|'
    r'\bconfig\s+[\'\"]?led\b|/lib/functions/leds\.sh')


def official_hashes(root):
    release = (root / 'etc/openwrt_release').read_text()
    source = os.environ.get('MX_OFFICIAL_SOURCE')
    if not source:
        if "DISTRIB_RELEASE='25.12.2'" not in release:
            raise AssertionError('set MX_OFFICIAL_SOURCE to the matching official source; fallback covers only 25.12.2')
        return NATIVE_LED_SHA256
    def git(*args):
        return subprocess.check_output(['git', '-C', source, *args], stderr=subprocess.DEVNULL)
    origin = git('remote', 'get-url', 'origin').decode().strip().removesuffix('.git')
    if origin != 'https://github.com/immortalwrt/immortalwrt':
        raise AssertionError('MX_OFFICIAL_SOURCE must identify the official ImmortalWrt origin')
    sha = git('rev-parse', '--verify', 'HEAD').decode().strip()
    revision = re.search(r"^DISTRIB_REVISION='(r[0-9]+-([0-9a-f]{7,40}))'$", release, re.M)
    stable = re.search(r"^DISTRIB_RELEASE='([0-9]+\.[0-9]+\.[0-9]+)'$", release, re.M)
    if stable:
        native_revision = git('show', 'HEAD:version').decode().strip()
        version_mk = git('show', 'HEAD:include/version.mk').decode()
        native_version = re.search(
            r'^VERSION_NUMBER:=\$\(if \$\(VERSION_NUMBER\),\$\(VERSION_NUMBER\),([0-9]+\.[0-9]+\.[0-9]+)\)$',
            version_mk, re.M)
        if (not revision or revision[1] != native_revision or not native_version or
                stable[1] != native_version[1]):
            raise AssertionError('installed stable version/revision does not match MX_OFFICIAL_SOURCE HEAD')
    elif not revision or not sha.startswith(revision[2]):
        raise AssertionError('installed root revision does not match MX_OFFICIAL_SOURCE HEAD')
    result = {}
    for name in NATIVE_LED_SHA256:
        path = ('target/linux/qualcommax/ipq807x/base-files/etc/board.d/01_leds'
                if name == 'etc/board.d/01_leds' else 'package/base-files/files/' + name)
        result[name] = hashlib.sha256(git('show', 'HEAD:' + path)).hexdigest()
    return result


class NativeLEDContractTests(unittest.TestCase):
    def assert_no_extra_led_policy(self, root, native=False):
        for directory in ('etc', 'lib', 'sbin', 'usr/bin', 'usr/sbin', 'usr/libexec'):
            for path in (root / directory).rglob('*'):
                rel = str(path.relative_to(root))
                if native and (rel in NATIVE_LED_SHA256 or rel.startswith('lib/apk/')):
                    continue
                if path.is_symlink() or not path.is_file():
                    continue
                raw = path.read_bytes()
                if b'\0' not in raw:
                    self.assertIsNone(LED_POLICY.search(raw.decode(errors='replace')),
                                      'unexpected LED policy: ' + rel)

    def assert_native_led_file(self, rel, raw, expected=None):
        self.assertEqual(hashlib.sha256(raw).hexdigest(), (expected or NATIVE_LED_SHA256)[rel], rel)

    def test_snapshot_expected_hashes_use_matching_official_git_objects(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            source, root = Path(tmp) / 'source', Path(tmp) / 'root'
            source.mkdir()
            (root / 'etc').mkdir(parents=True)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(source), *args],
                                               stderr=subprocess.DEVNULL, text=True).strip()
            git('init', '-q')
            git('remote', 'add', 'origin', 'https://github.com/immortalwrt/immortalwrt.git')
            for name in NATIVE_LED_SHA256:
                path = source / ('target/linux/qualcommax/ipq807x/base-files/etc/board.d/01_leds'
                                 if name == 'etc/board.d/01_leds' else 'package/base-files/files/' + name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('source-object fixture: ' + name)
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'source metadata fixture; not firmware')
            sha = git('rev-parse', 'HEAD')
            release = root / 'etc/openwrt_release'
            release.write_text("DISTRIB_RELEASE='SNAPSHOT'\nDISTRIB_REVISION='r1-" + sha[:10] + "'\n")
            with patch.dict(os.environ, MX_OFFICIAL_SOURCE=str(source)):
                expected = official_hashes(root)
                for name in NATIVE_LED_SHA256:
                    self.assertEqual(expected[name], hashlib.sha256(('source-object fixture: ' + name).encode()).hexdigest())
                # Dirty worktree cannot bless a changed expected hash.
                (source / 'package/base-files/files/etc/diag.sh').write_text('customized worktree must be ignored')
                self.assertEqual(expected, official_hashes(root))
                release.write_text("DISTRIB_RELEASE='SNAPSHOT'\nDISTRIB_REVISION='r1-0000000000'\n")
                with self.assertRaisesRegex(AssertionError, 'does not match'):
                    official_hashes(root)
                release.write_text("DISTRIB_RELEASE='SNAPSHOT'\nDISTRIB_REVISION='r1-" + sha[:10] + "'\n")
                git('remote', 'set-url', 'origin', 'https://example.invalid/fork')
                with self.assertRaisesRegex(AssertionError, 'official ImmortalWrt origin'):
                    official_hashes(root)
            with patch.dict(os.environ, MX_OFFICIAL_SOURCE=''):
                with self.assertRaisesRegex(AssertionError, 'fallback covers only 25.12.2'):
                    official_hashes(root)

    def test_stable_expected_hashes_use_release_version_not_tag_sha(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            source, root = Path(tmp) / 'source', Path(tmp) / 'root'
            source.mkdir()
            (root / 'etc').mkdir(parents=True)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(source), *args],
                                               stderr=subprocess.DEVNULL, text=True).strip()
            git('init', '-q')
            git('remote', 'add', 'origin', 'https://github.com/immortalwrt/immortalwrt.git')
            for name in NATIVE_LED_SHA256:
                path = source / ('target/linux/qualcommax/ipq807x/base-files/etc/board.d/01_leds'
                                 if name == 'etc/board.d/01_leds' else 'package/base-files/files/' + name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('stable source object: ' + name)
            (source / 'version').write_text('r123-abcdef0123\n')
            (source / 'include').mkdir()
            (source / 'include/version.mk').write_text(
                'VERSION_NUMBER:=$(call qstrip,$(CONFIG_VERSION_NUMBER))\n'
                'VERSION_NUMBER:=$(if $(VERSION_NUMBER),$(VERSION_NUMBER),26.01.0)\n')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'release tag object; not firmware')
            release = root / 'etc/openwrt_release'
            valid = "DISTRIB_RELEASE='26.01.0'\nDISTRIB_REVISION='r123-abcdef0123'\n"
            release.write_text(valid)
            with patch.dict(os.environ, MX_OFFICIAL_SOURCE=str(source)):
                expected = official_hashes(root)
                self.assertEqual(expected['etc/diag.sh'],
                                 hashlib.sha256(b'stable source object: etc/diag.sh').hexdigest())
                self.assertFalse(git('rev-parse', 'HEAD').startswith('abcdef0123'))
                (source / 'version').write_text('r999-0000000000\n')
                (source / 'include/version.mk').write_text('VERSION_NUMBER:=99.99.99\n')
                (source / 'package/base-files/files/etc/diag.sh').write_text('dirty LED policy')
                self.assertEqual(expected, official_hashes(root), 'ignore dirty native version and LED files')
                for broken in (valid.replace('26.01.0', '26.01.1'),
                               valid.replace('r123-abcdef0123', 'r999-0000000000')):
                    release.write_text(broken)
                    with self.assertRaisesRegex(AssertionError, 'does not match'):
                        official_hashes(root)

    @unittest.skipUnless(os.environ.get('MX_OFFICIAL_SOURCE'),
                         'set MX_OFFICIAL_SOURCE for real stable Git-object evidence')
    def test_real_stable_source_native_led_evidence(self):
        source = os.environ['MX_OFFICIAL_SOURCE']
        def git(*args):
            return subprocess.check_output(['git', '-C', source, *args], text=True).strip()
        version_mk = git('show', 'HEAD:include/version.mk')
        match = re.search(
            r'^VERSION_NUMBER:=\$\(if \$\(VERSION_NUMBER\),\$\(VERSION_NUMBER\),([0-9]+\.[0-9]+\.[0-9]+)\)$',
            version_mk, re.M)
        if not match:
            self.skipTest('real source is not a numeric stable release')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'etc').mkdir()
            (root / 'etc/openwrt_release').write_text(
                f"DISTRIB_RELEASE='{match[1]}'\nDISTRIB_REVISION='{git('show', 'HEAD:version')}'\n")
            expected = official_hashes(root)
            self.assertEqual(set(expected), set(NATIVE_LED_SHA256))
            if match[1] == '25.12.2':
                self.assertEqual(expected, NATIVE_LED_SHA256)
            for name in expected:
                path = ('target/linux/qualcommax/ipq807x/base-files/etc/board.d/01_leds'
                        if name == 'etc/board.d/01_leds' else 'package/base-files/files/' + name)
                raw = subprocess.check_output(['git', '-C', source, 'show', 'HEAD:' + path])
                self.assert_native_led_file(name, raw, expected)
                with self.assertRaises(AssertionError):
                    self.assert_native_led_file(name, raw + b'\ncustom LED policy\n', expected)

    def test_actual_installed_native_leds(self):
        selected = roots()
        if not selected:
            self.skipTest('set MX_ROOTFS_BASE or MX_MENU_ROOT + MX_MENU_DEVICE')
        for device, root in selected:
            with self.subTest(device=device):
                expected = official_hashes(root)
                for rel in NATIVE_LED_SHA256:
                    self.assert_native_led_file(rel, (root / rel).read_bytes(), expected)
                self.assert_no_extra_led_policy(root, native=True)

    def test_actual_native_file_mutations_are_rejected(self):
        selected = roots()
        if not selected:
            self.skipTest('set MX_ROOTFS_BASE or MX_MENU_ROOT + MX_MENU_DEVICE')
        for device, root in selected:
            expected = official_hashes(root)
            for rel in NATIVE_LED_SHA256:
                with self.subTest(device=device, path=rel):
                    raw = (root / rel).read_bytes()
                    self.assert_native_led_file(rel, raw, expected)
                    with self.assertRaises(AssertionError):
                        self.assert_native_led_file(rel, raw + b'\necho 0 > /sys/class/leds/blue:status/brightness\n', expected)

    def test_differently_named_runtime_led_policies_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, text in (
                ('etc/init.d/network-health', 'echo 1 > /sys/class/leds/blue:status/brightness\n'),
                ('etc/hotplug.d/iface/97-connectivity', '. /lib/functions/leds.sh\nstatus_led_on\n'),
                ('etc/uci-defaults/87-network', "uci set system.indicator=led\n"),
                ('etc/config/system', "config led 'indicator'\n option trigger 'netdev'\n"),
                ('lib/upgrade/finish.sh', 'led_set_attr blue:status trigger none\n'),
            ):
                with self.subTest(path=rel):
                    path = root / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
                    with self.assertRaisesRegex(AssertionError, 'LED policy'):
                        self.assert_no_extra_led_policy(root)
                    path.unlink()

    def test_no_led_preset_or_custom_runtime_owner(self):
        self.assert_no_extra_led_policy(REPO / 'user/default/files')
        for path in (
            'user/default/files/etc/uci-defaults/98-mx4200-leds',
            'user/default/files/etc/hotplug.d/iface/95-mx4200-led',
            'user/default/files/etc/init.d/mx4200-led',
            'user/default/files/lib/upgrade/zz-mx4200-led.sh',
        ):
            self.assertFalse((REPO / path).exists(), path)


if __name__ == '__main__':
    unittest.main()
