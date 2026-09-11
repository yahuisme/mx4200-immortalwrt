import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'files/sbin/tempinfo'


class TemperatureTest(unittest.TestCase):
    def test_named_sensors_and_disabled_radios(self):
        self.assertTrue(SCRIPT.exists(), 'MX4200 sensor reader missing')
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            for number, name, value in [(0, 'nss_top_thermal', '59700'),
                                        (5, 'cpu0_thermal', '60100'),
                                        (6, 'cpu1_thermal', '60700'),
                                        (9, 'cluster_thermal', '61000'),
                                        (12, 'ath11k_hwmon', None),
                                        (14, 'ath11k_hwmon', '55000')]:
                h = root / ('hwmon' + str(number))
                h.mkdir()
                (h / 'name').write_text(name + '\n')
                if value:
                    (h / 'temp1_input').write_text(value + '\n')
            code = SCRIPT.read_text().replace('/sys/class/hwmon', str(root))
            result = subprocess.run(['sh'], input=code, text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.strip(), 'CPU: 61.0°C, WiFi: 55.0°C')
            self.assertEqual(result.stderr, '')
            (root / 'hwmon14/temp1_input').unlink()
            result = subprocess.run(['sh'], input=code, text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.strip(), 'CPU: 61.0°C')


if __name__ == '__main__':
    unittest.main()
