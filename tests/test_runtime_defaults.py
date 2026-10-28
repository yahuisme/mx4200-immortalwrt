"""Run first-boot defaults in ash with private paths and a harmless UCI boundary."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / 'user/default/files/etc/uci-defaults/99-mx4200-defaults'


class RuntimeDefaultsTests(unittest.TestCase):
    def run_defaults(self, board='linksys,mx4200v2', missing='', fail='', retained=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'board_name').write_text(board)
            if retained:
                (root / 'sysupgrade.tar').touch()
            text = DEFAULTS.read_text()
            for before, after in (
                ('/tmp/sysinfo/board_name', str(root / 'board_name')),
                ('/tmp/sysinfo/model', str(root / 'model')),
                ('/sysupgrade.tgz', str(root / 'sysupgrade.tgz')),
                ('/tmp/sysupgrade.tar', str(root / 'sysupgrade.tar')),
            ):
                text = text.replace(before, after)
            script = root / 'defaults'
            script.write_text(text)
            # The real boot service sources each script in a subshell and removes
            # it only on success. No UCI executable or host config is touched.
            boundary = '''
uci() {
    shift
    case "$1" in
        get)
            [ "$2" != "$MISSING" ] || return 1
            case "$2" in
                wireless.radio[012]) printf 'wifi-device\\n';;
                wireless.radio0.htmode) printf 'HE80\\n';;
                *) return 1;;
            esac;;
        set)
            printf '%s\\n' "$2" >> "$LOG"
            [ "${2%%=*}" != "$FAIL" ];;
        *) return 99;;
    esac
}
( . "$SCRIPT" ) && exit 0
exit 1
'''
            result = subprocess.run(['/usr/bin/busybox', 'ash', '-c', boundary],
                                    env=dict(os.environ, SCRIPT=str(script),
                                             LOG=str(root / 'calls'),
                                             MISSING=missing, FAIL=fail),
                                    capture_output=True, text=True)
            calls = (root / 'calls').read_text().splitlines() if (root / 'calls').exists() else []
            return result, calls

    def test_both_models_and_retained_config(self):
        for board, hostname in (('linksys,mx4200v1', 'MX4200v1'),
                                ('linksys,mx4200v2', 'MX4200v2')):
            result, calls = self.run_defaults(board=board)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('system.@system[0].hostname=' + hostname, calls)
            self.assertIn('wireless.radio0.disabled=1', calls)
            self.assertIn('wireless.radio1.disabled=0', calls)
            self.assertIn('wireless.radio2.disabled=0', calls)
            self.assertIn('wireless.radio2.htmode=HE80', calls)
        result, calls = self.run_defaults(retained=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_missing_radio_keeps_script_for_later_boot(self):
        for radio in ('radio0', 'radio1', 'radio2'):
            result, calls = self.run_defaults(missing='wireless.' + radio)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])

    def test_each_failed_write_keeps_script_for_later_boot(self):
        _, expected = self.run_defaults()
        self.assertTrue(expected)
        for index, assignment in enumerate(expected):
            with self.subTest(assignment=assignment):
                result, calls = self.run_defaults(fail=assignment.split('=')[0])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, expected[:index + 1])


if __name__ == '__main__':
    unittest.main()
