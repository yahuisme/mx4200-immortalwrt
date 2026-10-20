"""Exercise the real autocore shell reader with isolated sysfs inputs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('MX4200_PRISTINE_SOURCE'),
                     'set MX4200_PRISTINE_SOURCE for real autocore reader')
class TemperatureTests(unittest.TestCase):
    def run_reader(self, samples, broken=(), patched=True):
        source = Path(os.environ['MX4200_PRISTINE_SOURCE'])
        relative = 'package/emortal/autocore/files/tempinfo'
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_bytes((source / relative).read_bytes())
            if patched:
                subprocess.run(['python3', str(ROOT / 'scripts/temperature.py'), d], check=True)
                before = target.read_bytes()
                subprocess.run(['python3', str(ROOT / 'scripts/temperature.py'), d], check=True)
                self.assertEqual(target.read_bytes(), before)
            ieee = root / 'ieee'
            thermal = root / 'thermal'
            for phy, value in samples.items():
                p = ieee / f'phy{phy}/hwmon{phy}/temp1_input'
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(value)
            for phy in broken:
                p = ieee / f'phy{phy}/hwmon{phy}/temp1_input'
                p.parent.mkdir(parents=True, exist_ok=True)
                p.symlink_to('/proc/self/mem')  # read returns EIO, even for root
            text = target.read_text().replace('. /etc/openwrt_release', "DISTRIB_TARGET='qualcommax/ipq807x'")
            text = text.replace('/sys/class/ieee80211', str(ieee)).replace('/sys/class/thermal', str(thermal))
            target.write_text(text)
            bindir = root / 'bin'
            bindir.mkdir()
            (bindir / 'awk').symlink_to('/usr/bin/busybox')
            return subprocess.run(['/usr/bin/busybox', 'ash', str(target)],
                                  env=os.environ | {'PATH': str(bindir)},
                                  capture_output=True, text=True, check=True).stdout

    def test_each_single_radio_and_three_radios(self):
        for phy in (0, 1, 2):
            with self.subTest(phy=phy):
                self.assertEqual(self.run_reader({phy: '47000\n'}), 'WiFi: 47.0°C')
        self.assertEqual(self.run_reader({0: '43000\n', 1: '44000\n', 2: '45000\n'}),
                         'WiFi: 43.0°C 44.0°C 45.0°C')

    def test_only_high_5g_readable_earlier_radios_eio(self):
        self.assertEqual(self.run_reader({2: '51000\n'}, broken=(0, 1)), 'WiFi: 51.0°C')

    def test_invalid_or_absent_values_are_not_zero(self):
        self.assertEqual(self.run_reader({0: 'bad\n', 1: '', 2: '49000\n'}), 'WiFi: 49.0°C')
        self.assertEqual(self.run_reader({}, broken=(0, 1, 2)), 'No temperature info')
        self.assertEqual(self.run_reader({}), 'No temperature info')

    def test_official_reader_reproduces_eio_suppression(self):
        self.assertEqual(self.run_reader({2: '51000\n'}, broken=(0, 1), patched=False),
                         'No temperature info')
