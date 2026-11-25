"""Replay official uci_apply_defaults in ash with private native UCI configs."""
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'user/default/files'
BOOT = ROOT / 'tests/fixtures/mx4200-native-boot.sh'
UCI = Path(os.environ.get('MX_TEST_UCI', '/opt/test-tools/openwrt/bin/uci')).resolve()


class DefaultsFixture:
    def __init__(self, root, script):
        self.root = root
        self.cfg = root / 'etc/config'
        self.cfg.mkdir(parents=True)
        self.delta = root / 'shared-deltas'
        self.delta.mkdir()
        (root / 'tmp/sysinfo').mkdir(parents=True)
        self.board = root / 'tmp/sysinfo/board_name'
        self.board.write_text('linksys,mx4200v2\n')
        self.set_files({'system': "config system\n option hostname 'ImmortalWrt'\n option timezone 'GMT0'\n option zonename 'UTC'\n",
                        'network': "config interface 'lan'\n option ipaddr '192.168.10.1'\n",
                        'aurora': "config aurora 'theme'\n option nav_type 'mega-menu'\n option struct_radius_base '0.5rem'\n option config_version '7'\n option light_brand '#0086bf'\n"})
        self.wifi()
        defaults = root / 'etc/uci-defaults'
        defaults.mkdir()
        self.script = defaults / script
        helper = '/lib/functions/mx4200-defaults.sh'
        (root / 'defaults-helper').write_text((FILES / helper[1:]).read_text().replace('/etc/', str(root / 'etc') + '/'))
        text = (FILES / 'etc/uci-defaults' / script).read_text()
        for name in (helper, '/sysupgrade.tgz', '/tmp/sysupgrade.tar', '/tmp/sysinfo/board_name', '/tmp/sysinfo/model'):
            target = root / (name[1:] if name != helper else 'defaults-helper')
            text = text.replace(name, str(target))
        self.script.write_text(text)
        # Extract the official function verbatim except private data paths and
        # the unneeded system.sh import; never run boot(), sync or services.
        boot = BOOT.read_text().split('\nboot() {', 1)[0]
        self.shell = boot.replace('\t. /lib/functions/system.sh', '\t:')
        self.shell = self.shell.replace('/etc/uci-defaults', str(defaults))

    def set_files(self, configs):
        for name, data in configs.items():
            (self.cfg / name).write_text(data)

    def wifi(self, missing=-1, bands=('5g', '2g', '5g'), channels=(36, 1, 100), path_indices=('', '+1', '+2'), wrong_iface=False, extra=False):
        records = []
        for i in range(3):
            if i == missing:
                continue
            records.append(f"""config wifi-device 'radio{i}'
 option type 'mac80211'
 option path 'platform/soc@0/c000000.wifi{path_indices[i]}'
 option band '{bands[i]}'
 option channel '{channels[i]}'
 option htmode '{'HE80' if i == 0 else 'HE20'}'
config wifi-iface 'default_radio{i}'
 option device 'radio{2 if wrong_iface else i}'
 option mode 'ap'
 option network 'lan'
 option ssid 'MX4200'
 option key '12345678'
""")
        if extra:
            records.append("config wifi-device 'extra'\n option band '6g'\n")
        self.set_files({'wireless': '\n'.join(records)})

    def uci(self, *args):
        return subprocess.check_output([str(UCI), '-q', '-c', str(self.cfg), '-C', '', '-t', str(self.delta), *args],
                                       text=True).strip()

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.cfg.iterdir() if p.is_file()}

    def boot(self, fail='', fail_commit='', fail_publish='', corrupt_commit=''):
        # Wrapper intercepts only injected operations. Explicit -t/-c keeps
        # even native commit confined; no host changes or service calls.
        boundary = '''
uci() {
    case " $* " in
        *" set $FAIL="*) [ -z "$FAIL" ] || return 72 ;;
        *" commit $FAIL_COMMIT "*) [ -z "$FAIL_COMMIT" ] || return 73 ;;
    esac
    printf '%s\\n' "$*" >> "$LOG"
    "$NATIVE_UCI" -c "$CONFIG_DIR" -C '' -t "$DELTA_DIR" "$@" || return $?
    case " $* " in
        *" commit $CORRUPT_COMMIT "*)
            [ -z "$CORRUPT_COMMIT" ] || printf '%s\\n' "config wifi-device 'radio0'" > "$CONFIG_DIR"/.mx4200-*/next/"$CORRUPT_COMMIT" ;;
    esac
}
mv() {
    case "$*" in
        *"/next/$FAIL_PUBLISH "*) [ -z "$FAIL_PUBLISH" ] || return 74 ;;
    esac
    command mv "$@"
}
sync() { :; }
'''
        return subprocess.run(['/usr/bin/busybox', 'ash', '-ec', boundary + self.shell + '\nuci_apply_defaults\n'],
                              cwd=self.root, env=dict(os.environ, NATIVE_UCI=str(UCI), CONFIG_DIR=str(self.cfg),
                                                      DELTA_DIR=str(self.delta), LOG=str(self.root / 'calls'),
                                                      FAIL=fail, FAIL_COMMIT=fail_commit, FAIL_PUBLISH=fail_publish,
                                                      CORRUPT_COMMIT=corrupt_commit),
                              capture_output=True, text=True, check=True)


class RuntimeDefaultsTests(unittest.TestCase):
    def test_complete_native_boot_and_all_models(self):
        for model, host in (('mx4200v1', 'MX4200v1'), ('mx4200v2', 'MX4200v2'), ('mx4300', 'MX4300'), ('homewrk', 'HomeWRK')):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as tmp:
                fixture = DefaultsFixture(Path(tmp), '99-mx4200-defaults')
                fixture.board.write_text(f'linksys,{model}')
                fixture.uci('add_list', 'system.@system[0].extra=earlier-boot-default')
                fixture.boot()
                self.assertFalse(fixture.script.exists())
                self.assertEqual(fixture.uci('get', 'system.@system[0].hostname'), host)
                self.assertEqual(fixture.uci('get', 'system.@system[0].extra'), 'earlier-boot-default')
                self.assertEqual(fixture.uci('get', 'system.@system[0].zonename'), 'Asia/Hong_Kong')
                self.assertEqual(fixture.uci('get', 'wireless.radio2.htmode'), 'HE80')
                for i, (chan, power, disabled) in enumerate(((48, 25, 1), (11, 23, 0), (149, 25, 0))):
                    for opt, val in dict(channel=chan, txpower=power, disabled=disabled, country='US').items():
                        self.assertEqual(fixture.uci('get', f'wireless.radio{i}.{opt}'), str(val))
                    self.assertEqual(fixture.uci('get', f'wireless.default_radio{i}.ssid'),
                                     'MX4300' if model in ('mx4300', 'homewrk') else 'MX4200')

    def test_partial_set_commit_or_publish_failure_is_not_globally_committed(self):
        for opts in ({'fail': 'wireless.radio2.txpower'}, {'fail_commit': 'wireless'}, {'fail_publish': 'wireless'},
                     {'corrupt_commit': 'wireless'}):
            with self.subTest(opts=opts), tempfile.TemporaryDirectory() as tmp:
                fixture = DefaultsFixture(Path(tmp), '99-mx4200-defaults')
                previous = fixture.snapshot()
                fixture.boot(**opts)
                self.assertTrue(fixture.script.exists())
                self.assertEqual(fixture.snapshot(), previous)
                self.assertFalse(list(fixture.cfg.glob('.mx4200-*')))
                self.assertEqual(fixture.uci('changes'), '')

    def test_missing_or_drifted_radios_leave_native_configuration_and_never_retry_user_settings(self):
        variants: tuple[dict[str, Any], ...] = (dict(missing=1), dict(bands=('5g', '5g', '2g')), dict(extra=True),
                     dict(path_indices=('', '+2', '+1')), dict(channels=(149, 1, 36)), dict(wrong_iface=True))
        for wifi in variants:
            with self.subTest(wifi=wifi), tempfile.TemporaryDirectory() as tmp:
                fixture = DefaultsFixture(Path(tmp), '99-mx4200-defaults')
                fixture.board.write_text('linksys,homewrk')
                fixture.wifi(**wifi)
                previous = fixture.snapshot()
                fixture.boot()
                self.assertTrue(fixture.script.exists())
                self.assertEqual(fixture.snapshot(), previous)
                fixture.wifi()
                fixture.uci('set', 'wireless.default_radio0.ssid=Personal')
                fixture.uci('set', 'system.@system[0].hostname=Personal')
                fixture.uci('set', 'network.lan.ipaddr=192.168.50.1')
                fixture.uci('commit')
                previous = fixture.snapshot()
                fixture.boot()
                self.assertEqual(fixture.snapshot(), previous)
                self.assertFalse(fixture.script.exists())

    def test_system_retained_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = DefaultsFixture(Path(tmp), '99-mx4200-defaults')
            (fixture.root / 'sysupgrade.tgz').touch()
            previous = fixture.snapshot()
            fixture.boot()
            self.assertEqual(fixture.snapshot(), previous)
            self.assertFalse(fixture.script.exists())
            self.assertFalse(list((fixture.root / 'etc').glob('.mx4200-*')))
