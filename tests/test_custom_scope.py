"""Execute current customization without requiring an unselected TLS recipe."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CUSTOM = ROOT / 'user/default/custom.sh'


class CustomScopeTests(unittest.TestCase):
    def test_customization_does_not_read_unselected_gnutls(self):
        for temperature_status in ('0', '17'):
            with self.subTest(temperature_status=temperature_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'package').mkdir()
                (root / 'tmp/info').mkdir(parents=True)
                (root / 'tmp/.packageinfo').write_text('old metadata')
                env = dict(os.environ, DK_OPENWRT=tmp, LOG=str(root / 'calls'),
                           TEMP_STATUS=temperature_status)
                boundary = '''
bash() {
    case "$1" in
        /cache-scripts/packages.sh) printf 'packages\\n' >> "$LOG";;
        /cache-scripts/settings.sh) printf 'settings\\n' >> "$LOG";;
        *) return 98;;
    esac
}
python3() {
    [ "$1" = /cache-scripts/temperature.py ] || return 99
    printf 'temperature\\n' >> "$LOG"
    return "$TEMP_STATUS"
}
'''
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c', boundary + CUSTOM.read_text()],
                                        cwd=root, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, int(temperature_status), result.stderr)
                self.assertEqual((root / 'calls').read_text().splitlines(),
                                 ['packages', 'temperature', 'settings'] if temperature_status == '0'
                                 else ['packages', 'temperature'])
                self.assertEqual((root / 'tmp/.packageinfo').exists(), temperature_status != '0')
                self.assertEqual((root / 'tmp/info').exists(), temperature_status != '0')
                self.assertFalse((root / 'feeds/packages/libs/gnutls/Makefile').exists())


if __name__ == '__main__':
    unittest.main()
