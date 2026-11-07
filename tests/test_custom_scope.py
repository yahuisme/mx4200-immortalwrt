"""Execute current customization without requiring an unselected TLS recipe."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CUSTOM = ROOT / 'user/default/custom.sh'


def tree_contents(root):
    """Include empty directories, symlinks, modes and bytes, not just files."""
    result = {}
    for path in root.rglob('*'):
        mode = path.lstat().st_mode
        data = (os.readlink(path) if stat.S_ISLNK(mode) else
                path.read_bytes() if stat.S_ISREG(mode) else None)
        result[str(path.relative_to(root))] = (mode, data)
    return result


class CustomScopeTests(unittest.TestCase):
    def test_actual_custom_rejects_unreviewed_version_before_any_tree_writes(self):
        # Execute the complete production custom/packages scripts, with only the
        # container mount path relocated. Local real Git objects avoid network.
        cases = (
            ('unsupported', 'VERSION_NUMBER:=26.01.0\n', ''),
            ('malformed', 'VERSION_NUMBER:=SNAPSHOTgarbage\n', ''),
            ('override', 'VERSION_NUMBER:=SNAPSHOT\n', 'CONFIG_VERSION_NUMBER="26.01.0"\n'),
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            donor = base / 'donor'
            subprocess.run(['git', 'init', '-q', '-b', 'main', str(donor)], check=True)
            for name in ('luci-app-homeproxy', 'sing-box'):
                path = donor / name / 'Makefile'
                path.parent.mkdir()
                path.write_text('# local caller-regression recipe: ' + name + '\n')
            subprocess.run(['git', '-C', str(donor), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(donor), '-c', 'user.name=Fixture', '-c',
                            'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            config = base / 'gitconfig'
            subprocess.run(['git', 'config', '--file', str(config),
                            f'url.{donor.as_uri()}.insteadOf',
                            'https://github.com/yahuisme/packages.git'], check=True)
            hooks = base / 'hooks'
            hooks.mkdir()
            for name in ('packages.sh', 'external_packages.py', 'temperature.py', 'settings.sh'):
                (hooks / name).write_text((ROOT / 'scripts' / name).read_text().replace(
                    '/cache-scripts/', str(hooks) + '/'))
            custom = base / 'custom.sh'
            custom.write_text(CUSTOM.read_text().replace('/cache-scripts/', str(hooks) + '/'))
            for label, version, override in cases:
                with self.subTest(case=label):
                    root = base / label
                    for name in ('include', 'scripts', 'package', 'feeds/luci', 'feeds/packages',
                                 'tmp/info/empty', '.external-packages/empty'):
                        (root / name).mkdir(parents=True, exist_ok=True)
                    (root / 'include/version.mk').write_text(version)
                    (root / '.config').write_text(override)
                    (root / 'scripts/projectsmirrors.json').write_text(
                        'https://mirror.cn/source\nhttps://keep.example/source\n')
                    (root / '.custom-revisions.tsv').write_text('existing Git provenance\n')
                    (root / '.external-packages/provenance.json').write_text('existing APK provenance\n')
                    (root / 'tmp/.packageinfo').write_text('existing index\n')
                    for name in ('luci-app-homeproxy', 'sing-box'):
                        path = root / 'package' / name / 'Makefile'
                        path.parent.mkdir()
                        path.write_text('existing ' + name + '\n')
                        (root / 'feeds/luci' / name).symlink_to(root / 'package' / name)
                    before = tree_contents(base)
                    result = subprocess.run(['bash', str(custom)], cwd=root, capture_output=True,
                                            text=True, env=dict(os.environ, DK_OPENWRT=str(root),
                                            GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1',
                                            TMPDIR=tmp))
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('require reviewed ImmortalWrt snapshot', result.stderr)
                    self.assertEqual(before, tree_contents(base),
                                     'custom must reject before changing any fixture file/directory')

    def test_homewrk_guard_failure_stops_all_downstream_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'package').mkdir()
            (root / 'scripts').mkdir()
            mirror = root / 'scripts/projectsmirrors.json'
            mirror.write_text('https://mirror.cn/source\n')
            dts = root / 'target/linux/qualcommax/dts/ipq8174-homewrk.dts'
            dts.parent.mkdir(parents=True)
            dts.write_text('unsupported upstream layout\n')
            custom = CUSTOM.read_text().replace('/cache-scripts/', str(ROOT / 'scripts') + '/')
            boundary = '''
python3() {
    if [ "$1" = "$REAL_EXTERNAL" ]; then return 0; fi
    command python3 "$@"
}
'''
            before = tree_contents(root)
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', boundary + custom],
                                    cwd=root, capture_output=True, text=True,
                                    env=dict(os.environ, DK_OPENWRT=tmp,
                                             REAL_EXTERNAL=str(ROOT / 'scripts/external_packages.py')))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('review MAC protection', result.stderr)
            self.assertEqual(before, tree_contents(root))

    def test_customization_does_not_read_unselected_gnutls(self):
        for temperature_status in ('0', '17'):
            with self.subTest(temperature_status=temperature_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'package').mkdir()
                (root / 'include').mkdir()
                (root / 'include/version.mk').write_text('VERSION_NUMBER:=SNAPSHOT\n')
                (root / 'tmp/info').mkdir(parents=True)
                (root / 'tmp/.packageinfo').write_text('old metadata')
                dts = root / 'target/linux/qualcommax/dts/ipq8174-homewrk.dts'
                dts.parent.mkdir(parents=True)
                original_dts = (ROOT / 'tests/fixtures/homewrk/ipq8174-homewrk.dts').read_text()
                dts.write_text(original_dts)
                env = dict(os.environ, DK_OPENWRT=tmp, LOG=str(root / 'calls'),
                           HOMEWRK_HELPER=str(ROOT / 'scripts/homewrk_dts.py'),
                           TEMP_STATUS=temperature_status,
                           REAL_EXTERNAL=str(ROOT / 'scripts/external_packages.py'))
                boundary = '''
bash() {
    case "$1" in
        /cache-scripts/packages.sh) printf 'packages\\n' >> "$LOG";;
        /cache-scripts/settings.sh) printf 'settings\\n' >> "$LOG";;
        *) return 98;;
    esac
}
python3() {
    if [ "$1" = /cache-scripts/homewrk_dts.py ]; then
        printf 'homewrk\\n' >> "$LOG"
        shift
        command python3 "$HOMEWRK_HELPER" "$@"
        return "$?"
    fi
    if [ "$1" = /cache-scripts/external_packages.py ]; then
        [ "$2" = preflight ] && [ "$3" = "$DK_OPENWRT" ] || return 99
        printf 'preflight\\n' >> "$LOG"
        shift
        command python3 "$REAL_EXTERNAL" "$@"
        return "$?"
    fi
    [ "$1" = /cache-scripts/temperature.py ] || return 99
    printf 'temperature\\n' >> "$LOG"
    return "$TEMP_STATUS"
}
'''
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c', boundary + CUSTOM.read_text()],
                                        cwd=root, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, int(temperature_status), result.stderr)
                self.assertEqual((root / 'calls').read_text().splitlines(),
                                 ['preflight', 'homewrk', 'packages', 'temperature', 'settings'] if temperature_status == '0'
                                 else ['preflight', 'homewrk', 'packages', 'temperature'])
                self.assertIn('status = "disabled";', dts.read_text())
                self.assertEqual((root / 'tmp/.packageinfo').exists(), temperature_status != '0')
                self.assertEqual((root / 'tmp/info').exists(), temperature_status != '0')
                self.assertFalse((root / 'feeds/packages/libs/gnutls/Makefile').exists())


if __name__ == '__main__':
    unittest.main()
