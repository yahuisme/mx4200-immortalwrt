"""Execute BusyBox ash against isolated sysfs/ubus/UCI boundaries."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('TMPDIR', '/root/.hermes/cache/scratch'))


class WanLed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hermes-verify-', dir=SCRATCH)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for d in ('sys/class/leds', 'tmp/sysinfo', 'var/run', 'bin'):
            (self.root / d).mkdir(parents=True)
        self.board('linksys,mx4200v2')
        for color in ('blue', 'red', 'green'):
            d = self.root / 'sys/class/leds' / f'{color}:status'
            d.mkdir()
            for name, value in [('trigger', '[none] timer'), ('brightness', '0'), ('max_brightness', '255')]:
                (d / name).write_text(value)
        (self.root / 'var/run/mx4200-led-ready').touch()
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + ':' + os.environ['PATH'], STATE='true', ACTION='ifup', INTERFACE='wan')
        self.stub('uci', '''case "$*" in
*wan_led_interface) printf '%s' "$WAN";;
*wan_led) printf '%s' "$ENABLED";;
*leds_off) printf '%s' "$OFF";;
esac
''')
        self.stub('ubus', 'printf "%s\\n" "$*" >> "$CALLS"\n[ "$FAIL" != 1 ] || exit 1\nprintf \'{"up":%s}\\n\' "$STATE"\n')
        # Strict parser at the external jsonfilter boundary, not the LED logic.
        self.stub('jsonfilter', "exec python3 -c 'import json,sys; print(str(json.load(sys.stdin).get(\"up\",\"\")).lower())'\n")
        self.env['CALLS'] = str(self.root / 'calls')
        self.script = self.isolate('files/etc/hotplug.d/iface/95-mx4200-led')

    def stub(self, name, body):
        p = self.root / 'bin' / name
        p.write_text('#!/bin/sh\n' + body)
        p.chmod(0o755)

    def isolate(self, path):
        text = (ROOT / path).read_text()
        for prefix in ('/sys/class/leds', '/tmp/', '/var/run/', '/etc/diag.sh', '/etc/hotplug.d/iface/95-mx4200-led'):
            text = text.replace(prefix, str(self.root) + prefix)
        p = self.root / Path(path).name
        p.write_text(text)
        return p

    def board(self, name):
        (self.root / 'tmp/sysinfo/board_name').write_text(name)

    def run_led(self, **env):
        subprocess.run(['busybox', 'ash', str(self.script)], env=dict(self.env, **env), check=True, capture_output=True)

    def brightness(self):
        return tuple((self.root / f'sys/class/leds/{c}:status/brightness').read_text().strip() for c in ('blue', 'red', 'green'))

    def test_up_down_update_and_ppp_pending(self):
        for action, state, expected in [('ifup', 'true', ('51', '0', '0')), ('ifdown', 'false', ('0', '255', '0')), ('ifupdate', 'false', ('0', '255', '0')), ('ifdown', 'true', ('51', '0', '0'))]:
            self.run_led(ACTION=action, STATE=state)
            self.assertEqual(self.brightness(), expected)
        self.assertIn('network.interface.wan status', (self.root / 'calls').read_text())

    def test_v1_and_brightness_clamp(self):
        self.board('linksys,mx4200v1')
        self.run_led()
        self.assertEqual(self.brightness()[0], '255')
        (self.root / 'sys/class/leds/blue:status/max_brightness').write_text('31')
        self.run_led()
        self.assertEqual(self.brightness()[0], '31')

    def test_unrelated_interfaces_and_actions(self):
        for interface in ('lan', 'wan6', 'wifi'):
            self.run_led(INTERFACE=interface)
        self.run_led(ACTION='iflink')
        self.assertFalse((self.root / 'calls').exists())
        self.assertEqual(self.brightness(), ('0', '0', '0'))

    def test_configured_ipv6_only_interface(self):
        self.run_led(WAN='wan6', INTERFACE='wan6')
        self.assertEqual(self.brightness()[0], '51')
        self.assertIn('network.interface.wan6 status', (self.root / 'calls').read_text())

    def test_boot_and_unavailable_ubus(self):
        self.run_led(ACTION='boot', FAIL='1')
        self.assertEqual(self.brightness(), ('0', '0', '0'))
        self.run_led(ACTION='boot')
        self.assertEqual(self.brightness(), ('51', '0', '0'))
        for state in ('true', 'false'):
            self.run_led(STATE=state)
            before = self.brightness()
            self.run_led(FAIL='1')
            self.assertEqual(self.brightness(), before)
            for unknown in ('null', '123', 'malformed'):
                self.run_led(STATE=unknown)
                self.assertEqual(self.brightness(), before)
        self.stub('ubus', 'printf \'{}\\n\'\n')
        self.run_led()
        self.assertEqual(self.brightness(), before)

    def test_fixed_brightness_requires_opt_out(self):
        for color, value in (('blue', '17'), ('red', '23')):
            (self.root / f'sys/class/leds/{color}:status/brightness').write_text(value)
        self.run_led(ENABLED='0')
        self.assertEqual(self.brightness(), ('17', '23', '0'))
        self.run_led()
        self.assertEqual(self.brightness(), ('51', '0', '0'))

    def test_early_boot_and_opt_out(self):
        for env in ({'ENABLED': '0'}, {'OFF': '1'}):
            self.run_led(**env)
        (self.root / 'var/run/mx4200-led-ready').unlink()
        self.run_led()
        self.assertFalse((self.root / 'calls').exists())

    def test_native_triggers_preserved(self):
        for color in ('red', 'blue', 'green'):
            p = self.root / f'sys/class/leds/{color}:status/trigger'
            p.write_text('none [timer]')
            self.run_led()
            self.assertEqual(self.brightness(), ('0', '0', '0'))
            p.write_text('[none] timer')
        self.assertFalse((self.root / 'calls').exists())

    def test_upgrade_handoff_and_late_event(self):
        self.run_led(STATE='false')
        (self.root / 'etc').mkdir()
        (self.root / 'etc/diag.sh').write_text('set_state() { echo 0 > "' + str(self.root) + '/sys/class/leds/blue:status/brightness"; echo "none [timer]" > "' + str(self.root) + '/sys/class/leds/green:status/trigger"; }\n')
        hook = self.isolate('files/lib/upgrade/zz-mx4200-led.sh')
        subprocess.run(['busybox', 'ash', '-c', f'. "{hook}"; indicate_upgrade'], check=True)
        for state in ('true', 'false'):
            self.run_led(STATE=state)
            self.assertEqual(self.brightness()[:2], ('0', '0'))
        self.assertTrue((self.root / 'tmp/mx4200-led-upgrade').exists())

    def test_upgrade_at_each_write_boundary(self):
        # Insert only a synchronous scheduling seam in an isolated copy.
        # The actual upgrade hook runs to completion, then hotplug resumes.
        (self.root / 'etc').mkdir()
        (self.root / 'etc/diag.sh').write_text(
            'set_state() { echo 0 > "' + str(self.root) +
            '/sys/class/leds/blue:status/brightness"; echo "none [timer]" > "' +
            str(self.root) + '/sys/class/leds/green:status/trigger"; }\n')
        hook = self.isolate('files/lib/upgrade/zz-mx4200-led.sh')
        original = self.script.read_text()
        guard = '\t[ ! -e ' + str(self.root) + '/tmp/mx4200-led-upgrade ] || break\n'
        write = '\tprintf \'%s\\n\' "$value" > "$leds/$color:status/brightness"\n'
        cleanup = 'if [ -e ' + str(self.root) + '/tmp/mx4200-led-upgrade ]; then\n'
        for state in ('true', 'false'):
            for color in ('blue', 'red'):
                for boundary in ('before_guard', 'before_write', 'after_write', 'before_cleanup', 'after_cleanup'):
                    with self.subTest(state=state, color=color, boundary=boundary):
                        (self.root / 'tmp/mx4200-led-upgrade').unlink(missing_ok=True)
                        for channel in ('blue', 'red', 'green'):
                            (self.root / f'sys/class/leds/{channel}:status/trigger').write_text('[none] timer')
                            (self.root / f'sys/class/leds/{channel}:status/brightness').write_text('0')
                        seam = f'\tif [ "$color" = {color} ]; then . "{hook}"; indicate_upgrade; fi\n'
                        if boundary == 'before_guard':
                            text = original.replace(guard, seam + guard)
                        elif boundary == 'before_write':
                            text = original.replace(write, seam + write)
                        elif boundary == 'after_write':
                            text = original.replace(write, write + seam)
                        elif boundary == 'before_cleanup':
                            text = original.replace(cleanup, f'. "{hook}"; indicate_upgrade\n' + cleanup)
                        else:
                            text = original.replace('\n)', f'\n. "{hook}"; indicate_upgrade\n)')
                        self.assertNotEqual(text, original)
                        self.script.write_text(text)
                        self.run_led(STATE=state)
                        self.assertTrue((self.root / 'tmp/mx4200-led-upgrade').exists())
                        self.assertEqual(self.brightness()[:2], ('0', '0'))
                        self.assertEqual((self.root / 'sys/class/leds/green:status/trigger').read_text().strip(), 'none [timer]')
        self.script.write_text(original)

    def test_upgrade_begins_during_status_query(self):
        marker = self.root / 'tmp/mx4200-led-upgrade'
        self.stub('ubus', f'touch "{marker}"\nprintf \'{{"up":true}}\\n\'\n')
        self.run_led()
        self.assertEqual(self.brightness(), ('0', '0', '0'))

    def test_hotplug_returns_to_other_hooks(self):
        subprocess.run(['busybox', 'ash', '-c', f'. "{self.script}"; echo continued'], env=dict(self.env, INTERFACE='lan'), check=True, capture_output=True)
        result = subprocess.check_output(['busybox', 'ash', '-c', f'. "{self.script}"; echo continued'], env=dict(self.env, INTERFACE='lan'), text=True)
        self.assertEqual(result.strip(), 'continued')

    def test_other_board(self):
        self.board('other,board')
        self.run_led()
        self.assertFalse((self.root / 'calls').exists())

    def test_boot_entry_runs_once(self):
        p = self.root / 'etc/hotplug.d/iface'
        p.mkdir(parents=True)
        (p / '95-mx4200-led').write_text(self.script.read_text())
        boot = self.isolate('files/etc/init.d/mx4200-led')
        (self.root / 'var/run/mx4200-led-ready').unlink()
        subprocess.run(['busybox', 'ash', '-c', f'. "{boot}"; boot'], env=self.env, check=True)
        self.assertEqual(self.brightness(), ('51', '0', '0'))
        self.assertEqual(len((self.root / 'calls').read_text().splitlines()), 1)
