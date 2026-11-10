"""Run the actual tempinfo reader with private sysfs and failed reads."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/tempinfo.sh'
HELPER = ROOT / 'scripts/temperature.py'


class TemperatureTests(unittest.TestCase):
    def prepare(self, root):
        path = root / 'package/emortal/autocore/files/tempinfo'
        path.parent.mkdir(parents=True)
        path.write_bytes(FIXTURE.read_bytes())
        return path

    def apply(self, root):
        return subprocess.run(['python3', str(HELPER), str(root)],
                              capture_output=True, text=True)

    def render(self, root, source, states):
        ieee = root / 'ieee'
        thermal = root / 'thermal/thermal_zone0'
        thermal.mkdir(parents=True)
        (thermal / 'temp').write_text('60000\n')
        for phy, value in enumerate(states):
            path = ieee / f'phy{phy}/hwmon0/temp1_input'
            path.parent.mkdir(parents=True)
            if value is None:
                path.symlink_to('/proc/self/mem')  # open succeeds, read returns EIO
            else:
                path.write_text(value)
        script = source.replace('. /etc/openwrt_release', 'DISTRIB_TARGET=qualcommax/ipq807x')
        script = script.replace('/sys/class/ieee80211', str(ieee))
        script = script.replace('/sys/class/thermal', str(thermal.parent))
        script = 'awk() { busybox awk "$@"; }\n' + script
        return subprocess.run(['busybox', 'ash', '-c', script],
                              capture_output=True, text=True, env=dict(os.environ, LC_ALL='C'))

    def test_inactive_radios_do_not_hide_later_high_band(self):
        for fixed in (False, True):
            with self.subTest(fixed=fixed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = self.prepare(root)
                if fixed:
                    self.assertEqual(self.apply(root).returncode, 0)
                result = self.render(root, path.read_text(), [None, None, '77000\n'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertEqual(result.stdout, 'CPU: 60.0°C' + (', WiFi: 77.0°C' if fixed else ''))

    def test_valid_zero_negative_and_invalid_readings(self):
        cases = [([], 'CPU: 60.0°C'), ([None, None], 'CPU: 60.0°C'),
                 (['0\n', '-1000\n', '52000\n'], 'CPU: 60.0°C, WiFi: 0.0°C -1.0°C 52.0°C'),
                 (['bad\n', '\n', '65000\n'], 'CPU: 60.0°C, WiFi: 65.0°C')]
        for states, expected in cases:
            with self.subTest(states=states), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = self.prepare(root)
                self.assertEqual(self.apply(root).returncode, 0)
                result = self.render(root, path.read_text(), states)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertEqual(result.stdout, expected)

    def test_only_wifi_changes_and_repeat_is_noop(self):
        from scripts.temperature import OLD, NEW
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.prepare(root)
            for _ in range(2):
                result = self.apply(root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(path.read_text(), FIXTURE.read_text().replace(OLD, NEW, 1))
            text = path.read_text().replace(NEW, 'unsupported upstream reader')
            path.write_text(text)
            self.assertNotEqual(self.apply(root).returncode, 0)
            self.assertEqual(path.read_text(), text)


if __name__ == '__main__':
    unittest.main()
