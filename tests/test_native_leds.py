"""Ensure MX4200 does not install a custom LED preset or runtime owner."""
from pathlib import Path
import hashlib
import re
import tempfile
import unittest

from installed_rootfs import roots


REPO = Path(__file__).resolve().parents[1]
# Byte-for-byte official v25.12.2 source, commit below; not extracted-image
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

    def assert_native_led_file(self, rel, raw):
        self.assertEqual(hashlib.sha256(raw).hexdigest(), NATIVE_LED_SHA256[rel], rel)

    def test_actual_installed_native_leds(self):
        selected = roots()
        if not selected:
            self.skipTest('set MX_ROOTFS_BASE or MX_MENU_ROOT + MX_MENU_DEVICE')
        for device, root in selected:
            with self.subTest(device=device):
                for rel in NATIVE_LED_SHA256:
                    self.assert_native_led_file(rel, (root / rel).read_bytes())
                self.assert_no_extra_led_policy(root, native=True)

    def test_actual_native_file_mutations_are_rejected(self):
        selected = roots()
        if not selected:
            self.skipTest('set MX_ROOTFS_BASE or MX_MENU_ROOT + MX_MENU_DEVICE')
        for device, root in selected:
            for rel in NATIVE_LED_SHA256:
                with self.subTest(device=device, path=rel):
                    raw = (root / rel).read_bytes()
                    self.assert_native_led_file(rel, raw)
                    with self.assertRaises(AssertionError):
                        self.assert_native_led_file(rel, raw + b'\necho 0 > /sys/class/leds/blue:status/brightness\n')

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
