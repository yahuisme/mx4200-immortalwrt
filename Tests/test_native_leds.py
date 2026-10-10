"""Real UCI/ash/native LED integration in a disposable chroot, no mocked UCI.

Run as root with MX4200_TEST_ROOTFS pointing at an extracted, host-executable
OpenWrt/ImmortalWrt rootfs. Only sysfs/DT hardware files are fixtures; no mounts.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
ROOTFS = os.environ.get('MX4200_TEST_ROOTFS')


@unittest.skipUnless(ROOTFS and os.geteuid() == 0,
                     'requires root and MX4200_TEST_ROOTFS (real native UCI/ash)')
class NativeLEDTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hermes-verify-native-led-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        assert ROOTFS is not None
        source = Path(ROOTFS)
        for folder in ('bin', 'lib/functions', 'lib/config'):
            shutil.copytree(source / folder, self.root / folder, symlinks=True)
        for folder in ('etc/config', 'etc/init.d', 'sbin', 'tmp/sysinfo', 'var/run',
                       'dev', 'proc/device-tree/aliases'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for file in source.glob('lib/*.so*'):
            shutil.copy2(file, self.root / 'lib' / file.name, follow_symlinks=True)
        for file in ('sbin/uci', 'lib/functions.sh', 'etc/init.d/led', 'etc/diag.sh'):
            shutil.copy2(source / file, self.root / file)
        (self.root / 'dev/null').touch()
        (self.root / 'etc/config/system').write_text("config system 'main'\n")
        shutil.copy2(REPO / 'files/etc/uci-defaults/98-mx4200-leds', self.root / 'presets')
        for color in ('blue', 'green', 'red'):
            led = self.root / f'sys/class/leds/{color}:status'
            led.mkdir(parents=True)
            for name, value in {'brightness': '0', 'max_brightness': '255',
                                'trigger': '[none] timer netdev',
                                'delay_on': '0', 'delay_off': '0'}.items():
                (led / name).write_text(value)
            dt = self.root / f'proc/device-tree/led-{color}'
            dt.mkdir()
            (dt / 'label').write_bytes(f'{color}:status\0'.encode())
        for alias, color in {'boot': 'blue', 'running': 'blue',
                             'failsafe': 'red', 'upgrade': 'green'}.items():
            (self.root / f'proc/device-tree/aliases/led-{alias}').write_bytes(
                f'/led-{color}\0'.encode())
        self.board('linksys,mx4200v1')

    def shell(self, code):
        return subprocess.run(['chroot', str(self.root), '/bin/sh', '-c', code],
                              check=True, capture_output=True, text=True).stdout.strip()

    def board(self, name):
        (self.root / 'tmp/sysinfo/board_name').write_text(name)

    def presets(self):
        self.shell('/bin/sh /presets && uci commit system')

    def apply(self):
        self.shell('. /lib/functions.sh; extra_command() { :; }; '
                   '. /etc/init.d/led; start')

    def attr(self, color, name):
        return (self.root / f'sys/class/leds/{color}:status/{name}').read_text().strip()

    def test_both_revisions_native_application_and_idempotence(self):
        for revision, brightness in (('v1', '255'), ('v2', '51')):
            with self.subTest(revision=revision):
                (self.root / 'etc/config/system').write_text("config system 'main'\n")
                self.board('linksys,mx4200' + revision)
                self.presets()
                before = self.shell('uci export system')
                self.assertEqual(before.count('config led '), 3)
                self.presets()
                self.assertEqual(before, self.shell('uci export system'))
                self.apply()
                self.assertEqual([self.attr(c, 'brightness') for c in ('blue', 'green', 'red')],
                                 [brightness, '0', '0'])
                self.assertEqual([self.attr(c, 'trigger') for c in ('blue', 'green', 'red')],
                                 ['none'] * 3)

    def test_existing_renamed_anonymous_rules_and_name_collision(self):
        self.shell("uci add system led; uci set system.@led[-1].sysfs='blue:status'; "
                   "uci set system.@led[-1].trigger=timer; uci set system.@led[-1].delayon=700; "
                   "uci set system.led_red=other; uci commit system")
        self.presets()
        self.assertEqual(self.shell('uci get system.@led[0].trigger'), 'timer')
        self.assertEqual(self.shell('uci get system.@led[0].delayon'), '700')
        self.assertEqual(self.shell('uci get system.led_red'), 'other')
        self.assertEqual(self.shell('uci export system').count('config led'), 2)
        self.apply()
        self.assertEqual(self.attr('blue', 'trigger'), 'timer')
        self.assertEqual(self.attr('blue', 'delay_on'), '700')

    def test_native_v2_rules_left_byte_identical(self):
        self.board('linksys,mx4200v2')
        # Native config_generate output from the official brightness presets.
        for color in ('blue', 'green', 'red'):
            self.shell(f"uci set system.led_{color}=led; "
                       f"uci set system.led_{color}.name={color}; "
                       f"uci set system.led_{color}.sysfs={color}:status; "
                       f"uci set system.led_{color}.default={int(color == 'blue')}")
        self.shell('uci set system.led_blue.brightness=51; uci commit system')
        before = (self.root / 'etc/config/system').read_bytes()
        self.presets()
        self.assertEqual(before, (self.root / 'etc/config/system').read_bytes())

    def test_restored_upgrade_and_other_board_untouched(self):
        before = self.shell('uci export system')
        for marker in ('sysupgrade.tgz', 'tmp/sysupgrade.tar'):
            (self.root / marker).touch()
            self.presets()
            self.assertEqual(before, self.shell('uci export system'))
            (self.root / marker).unlink()
        self.board('other,board')
        self.presets()
        self.assertEqual(before, self.shell('uci export system'))

    def test_luci_style_edits_remain_owned_by_native_service(self):
        self.presets()
        self.shell('uci set system.led_blue.default=0; '
                   'uci set system.led_red.default=1; '
                   'uci set system.led_red.brightness=17; uci commit system')
        self.presets()
        self.apply()
        self.assertEqual(self.attr('blue', 'brightness'), '0')
        self.assertEqual(self.attr('red', 'brightness'), '17')
        self.shell('uci set system.main.leds_off=1; uci commit system')
        self.apply()
        self.assertEqual([self.attr(c, 'brightness') for c in ('blue', 'green', 'red')],
                         ['0'] * 3)

    def test_native_diagnostics_retain_ownership(self):
        self.presets()
        self.apply()
        self.shell('. /etc/diag.sh; set_state upgrade')
        self.assertEqual(self.attr('blue', 'brightness'), '0')
        self.assertEqual(self.attr('red', 'brightness'), '0')
        self.assertEqual(self.attr('green', 'trigger'), 'timer')
        self.assertEqual(self.attr('green', 'delay_on'), '200')
        self.shell('. /etc/diag.sh; set_state failsafe')
        self.assertEqual(self.attr('red', 'trigger'), 'timer')
        self.assertEqual(self.attr('red', 'delay_on'), '50')


class NativeLEDContractTests(unittest.TestCase):
    def test_no_custom_runtime_owner(self):
        for path in ('files/etc/hotplug.d/iface/95-mx4200-led',
                     'files/etc/init.d/mx4200-led',
                     'files/lib/upgrade/zz-mx4200-led.sh'):
            self.assertFalse((REPO / path).exists())
        text = (REPO / 'files/etc/uci-defaults/98-mx4200-leds').read_text()
        for forbidden in ('/sys/class/leds', 'ubus', 'sleep ', 'ping ', 'wan_led'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
