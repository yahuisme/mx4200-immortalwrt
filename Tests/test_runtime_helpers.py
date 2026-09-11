"""Run shipped helpers under BusyBox ash; never touch host networking."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def test_stats_restores_on_every_exit(self):
        source = (ROOT / 'package/qca-nss/qca-nss-drv/files/qca-nss-drv.debug').read_text()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stats = root / 'stats'
            stats.mkdir()
            (stats / 'cpu_load_ubi').write_text('cpu = 1\n')
            script = root / 'stats.sh'
            script.write_text('''sysctl() {
  if [ "$2" = -n ]; then
    [ "$OLD" != failed ] || return 1
    printf '%s\\n' "$OLD"
  else printf '%s\\n' "$*" >> "$CALLS"; fi
}
''' + source.replace('/sys/kernel/debug/qca-nss-drv/stats', str(stats)))
            for old in ('0', '1', '', 'failed'):
                for args, code in [(['help'], 0), (['missing'], 1), ([], 0)]:
                    with self.subTest(old=old, args=args):
                        calls = root / 'calls'
                        calls.write_text('')
                        result = subprocess.run(['busybox', 'ash', str(script), *args], env=dict(os.environ, OLD=old, CALLS=str(calls)), input='', text=True, capture_output=True)
                        if old in ('0', '1'):
                            self.assertEqual(result.returncode, code, result.stderr)
                            self.assertEqual(calls.read_text().splitlines(), ['-q dev.nss.stats.non_zero_stats=1', '-q dev.nss.stats.non_zero_stats=' + old])
                        else:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertEqual(calls.read_text(), '')

    def test_gro_query_and_setting_alias(self):
        source = (ROOT / 'package/qca-nss/qca-nss-ecm/files/disable_offloads.sh').read_text()
        function = source.split('disable_feature() {', 1)[1].split('\ndisable_flow_control()', 1)[0]
        for state, expected in [('on', '-K eth0 gro off'), ('off', ''), ('on [fixed]', '-K eth0 gro off'), ('', '')]:
            script = '''ethtool() {
  if [ "$1" = -k ]; then printf '%s\\n' "generic-receive-offload: $STATE" 'rx-gro-list: on';
  else printf '%s\\n' "$*"; fi
}
log() { :; }
''' + 'disable_feature() {' + function.replace('1> /dev/null 2> /dev/null', '') + '\ndisable_feature gro eth0\ndisable_feature rx-gro-list eth0\n'
            result = subprocess.run(['busybox', 'ash', '-c', script], env=dict(os.environ, STATE=state), text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.splitlines(), ([expected] if expected else []) + ['-K eth0 rx-gro-list off'])


if __name__ == '__main__':
    unittest.main()
