"""Ensure MX4200 does not install a custom LED preset or runtime owner."""
from pathlib import Path
import unittest


REPO = Path(__file__).resolve().parents[1]


class NativeLEDContractTests(unittest.TestCase):
    def test_no_led_preset_or_custom_runtime_owner(self):
        for path in (
            'user/default/files/etc/uci-defaults/98-mx4200-leds',
            'user/default/files/etc/hotplug.d/iface/95-mx4200-led',
            'user/default/files/etc/init.d/mx4200-led',
            'user/default/files/lib/upgrade/zz-mx4200-led.sh',
        ):
            self.assertFalse((REPO / path).exists(), path)


if __name__ == '__main__':
    unittest.main()
