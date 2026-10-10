"""Execute workflow boundaries without building or publishing firmware."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())
STEPS = {step['name']: step for step in WORKFLOW['jobs']['build']['steps']}


class WorkflowTests(unittest.TestCase):
    def run_block(self, name, root, env=None):
        code = STEPS[name]['run'].replace('/mnt/build_wrt', str(root))
        return subprocess.run(['bash', '-eo', 'pipefail', '-c', code], cwd=root,
                              env=dict(os.environ, **(env or {})), capture_output=True, text=True)

    def test_profile_excludes_usteer(self):
        lines = (ROOT / 'Config/MX4200.txt').read_text().splitlines()
        for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn'):
            symbol = 'CONFIG_PACKAGE_' + package
            with self.subTest(package=package):
                # Require explicit n in the input: absence permits upstream defaults.
                self.assertEqual([line for line in lines if line.startswith(symbol + '=')],
                                 [symbol + '=n'])
        self.assertNotIn('usteer', (ROOT / 'README.md').read_text().lower())
        for package in ('etherwake', 'luci-app-wol', 'ttyd', 'luci-app-ttyd'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=y', lines)

    def test_profile_omits_retired_fullcone_package(self):
        self.assertNotIn('CONFIG_PACKAGE_kmod-nft-fullcone',
                         (ROOT / 'Config/MX4200.txt').read_text())

    def test_release_scope(self):
        self.assertEqual(WORKFLOW['concurrency'], {'group': 'mx4200-build', 'cancel-in-progress': False})
        self.assertEqual(STEPS['Publish firmware and prune releases']['if'],
                         "${{ !cancelled() && github.ref == 'refs/heads/main' && steps.stage.outcome == 'success' }}")
        self.assertEqual(STEPS['Validate and stage firmware']['id'], 'stage')
        self.assertEqual(WORKFLOW['jobs']['build']['runs-on'], 'ubuntu-24.04')

    def test_cache_contract(self):
        ordered = list(STEPS)
        self.assertEqual(STEPS['Configure firmware and caches']['id'], 'keys')
        self.assertEqual(len(ordered), 21)
        self.assertLess(ordered.index('Configure firmware and caches'), ordered.index('Restore toolchain cache'))
        self.assertNotIn('restore-keys', STEPS['Restore toolchain cache']['with'])
        self.assertIn('rolling-prefix', STEPS['Restore downloads and ccache']['with']['restore-keys'])
        self.assertNotIn('staging_dir', STEPS['Restore toolchain cache']['with']['path'])
        for label in ('toolchain cache', 'downloads and ccache'):
            prune = 'Prune old ' + ('toolchain caches' if label == 'toolchain cache' else 'downloads and ccache')
            self.assertLess(ordered.index(prune), ordered.index('Publish firmware and prune releases'))
            self.assertLess(ordered.index('Pack ' + label), ordered.index('Save ' + label))
            self.assertLess(ordered.index('Save ' + label), ordered.index(prune))
            self.assertIn("github.ref == 'refs/heads/main'", STEPS['Pack ' + label]['if'])
            self.assertIn('admitted', STEPS['Save ' + label]['if'])
            self.assertIn("outcome == 'success'", STEPS[prune]['if'])
            self.assertEqual(STEPS['Restore ' + label]['with']['path'],
                             STEPS['Save ' + label]['with']['path'])
        self.assertLess(ordered.index('Prune old toolchain caches'), ordered.index('Pack downloads and ccache'))

    def test_source_preparation_handoff(self):
        self.assertEqual(STEPS['Prepare firmware source']['id'], 'go-bootstrap')
        self.assertEqual(STEPS['Install Go bootstrap']['with']['go-version'],
                         '${{ steps.go-bootstrap.outputs.version }}')
        order = ['clone', 'hash', 'version', 'update', 'install', 'revision',
                 'packages', 'gnutls', 'temperature', 'bootstrap']
        for failure in ['', *order]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace = root / 'workspace'
                for directory in ('scripts', 'package', 'feeds/packages/.git', 'feeds/packages.tmp',
                                  'workspace/Scripts', 'bin'):
                    (root / directory).mkdir(parents=True)
                # GITHUB_ENV is deliberately not sourced within this step.
                common = 'echo "$event" >> "$LOG"\n[ "$FAILURE" != "$event" ] || exit 7\n'
                stubs = {
                    root / 'bin/git': 'case "$1" in clone) event=clone;; rev-parse) event=hash;; -C) event=revision;; *) exit 8;; esac\n' + common + 'printf "%040d\\n" 1\n',
                    root / 'scripts/getver.sh': 'event=version\n' + common + 'echo r1234-abcdef0\n',
                    root / 'scripts/feeds': 'event="$1"\n' + common,
                    workspace / 'Scripts/Packages.sh': 'test "$PWD" = "$BUILD/package"\nevent=packages\n' + common,
                }
                for path, body in stubs.items():
                    path.write_text('#!/bin/bash -e\n' + body)
                    path.chmod(0o755)
                for name, event in [('GnuTLS.py', 'gnutls'), ('Temperature.py', 'temperature'),
                                    ('GoBootstrap.py', 'bootstrap')]:
                    (workspace / 'Scripts' / name).write_text(
                        'import os, sys\nfrom pathlib import Path\n'
                        'assert Path.cwd() == Path(sys.argv[1]) / "package"\n'
                        f'event = {event!r}\n'
                        'with open(os.environ["LOG"], "a") as f: f.write(event + "\\n")\n'
                        'if os.environ["FAILURE"] == event: sys.exit(7)\n' +
                        ('import runpy\n' + f'runpy.run_path({str(ROOT / "Scripts/GoBootstrap.py")!r}, run_name="__main__")\n'
                         if event == 'bootstrap' else ''))
                recipe = root / 'feeds/packages/lang/golang/golang-bootstrap/Makefile'
                recipe.parent.mkdir(parents=True)
                recipe.write_text('GO_VERSION_MAJOR_MINOR:=1.24\nGO_VERSION_PATCH:=7\n')
                result = self.run_block('Prepare firmware source', root, {
                    'GITHUB_WORKSPACE': str(workspace), 'GITHUB_OUTPUT': str(root / 'output'),
                    'GITHUB_ENV': str(root / 'env'), 'BUILD': str(root),
                    'WRT_REPO': 'fixture', 'WRT_BRANCH': 'master',
                    'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
                    'LOG': str(root / 'log'), 'FAILURE': failure})
                self.assertEqual(result.returncode == 0, not failure, result.stderr)
                expected = order[:order.index(failure) + 1] if failure else order
                self.assertEqual((root / 'log').read_text().splitlines(), expected)
                if failure:
                    self.assertFalse((root / 'output').exists())
                else:
                    self.assertEqual((root / 'output').read_text(), 'version=1.24.7\n')
                    self.assertIn('feeds/packages ' + '0' * 39 + '1', result.stdout)
                    self.assertNotIn('packages.tmp', result.stdout)
                    values = dict(line.split('=', 1) for line in (root / 'env').read_text().splitlines())
                    self.assertEqual(values['WRT_HASH'], '0' * 39 + '1')
                    self.assertEqual(values['WRT_RELEASE_NAME'],
                                     'MX4200_ImmortalWrt_' + values['WRT_DATE'] + '_r1234')
                    self.assertEqual(values['WRT_RELEASE_TITLE'],
                                     'MX4200-ImmortalWrt-r1234-' + values['WRT_DATE'].replace('-', '_', 1))

    def test_configuration_cache_key_handoff(self):
        order = ['go', 'settings', 'defconfig', 'keys', 'hostpkg']
        for failure in ['', *order]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace = root / 'workspace'
                for directory in ('Scripts', 'Config', 'files', 'bin'):
                    (workspace / directory).mkdir(parents=True)
                (workspace / 'Config/MX4200.txt').write_text('CONFIG_TEST=y\n')
                (workspace / 'files/marker').write_text('overlay')
                common = 'echo "$event" >> "$LOG"\n[ "$FAILURE" != "$event" ] || exit 7\n'
                (workspace / 'Scripts/Settings.sh').write_text('event=settings\n' + common)
                for command, body in {
                    'go': 'event=go\n' + common + 'printf "/fixture/go\\n"',
                    'make': 'test "$PWD" = "$BUILD"\nevent=defconfig\n' + common,
                    'python3': '''test "$PWD" = "$BUILD"
case "$1" in
  "$GITHUB_WORKSPACE/Scripts/Cache.py")
    event=keys
    ''' + common + '''
    test "$2" = --output
    test "$3" = "$GITHUB_OUTPUT"
    printf 'tc-key=fixture\nrolling-prefix=rolling-\nsource-files=42\n' >> "$GITHUB_OUTPUT"
    ;;
  "$GITHUB_WORKSPACE/Scripts/HostpkgCache.py")
    event=hostpkg
    ''' + common + '''
    test "$2" = "$BUILD"
    test "$3" = fixture
    test "$4" = /fixture/go
    echo hostpkg-key=host-fixture >> "$GITHUB_OUTPUT"
    ;;
  *) exit 8;;
esac
''',
                }.items():
                    stub = workspace / 'bin' / command
                    stub.write_text('#!/bin/bash -e\n' + body + '\n')
                    stub.chmod(0o755)
                result = self.run_block('Configure firmware and caches', root, {
                    'GITHUB_WORKSPACE': str(workspace), 'GITHUB_OUTPUT': str(root / 'output'),
                    'PATH': str(workspace / 'bin') + ':' + os.environ['PATH'],
                    'LOG': str(root / 'log'), 'FAILURE': failure, 'BUILD': str(root),
                    'TC_KEY': 'stale-environment-must-not-be-used',
                    'GITHUB_REF': 'refs/heads/main', 'ImageOS': 'ubuntu24', 'ImageVersion': 'fixture'})
                self.assertEqual(result.returncode == 0, not failure, result.stderr)
                expected = order[:order.index(failure) + 1] if failure else order
                self.assertEqual((root / 'log').read_text().splitlines(), expected)
                if not failure:
                    self.assertEqual((root / 'output').read_text(),
                                     'tc-key=fixture\nrolling-prefix=rolling-\nsource-files=42\nhostpkg-key=host-fixture\n')
                    self.assertEqual((root / 'files/marker').read_text(), 'overlay')
                    self.assertIn('CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT="/fixture/go"',
                                  (root / '.config').read_text())
                elif failure != 'hostpkg':
                    self.assertFalse((root / 'output').exists())

    def test_build_inputs_stop_before_download_on_unpack_failure(self):
        for failure in ('', 'tc', 'hostpkg', 'rolling', 'download', 'cold'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archives = root / 'archives'
                archives.mkdir()
                bindir = root / 'bin'
                bindir.mkdir()
                if failure != 'cold':
                    for tier in ('tc', 'hostpkg', 'rolling'):
                        (archives / (tier + '.tar.gz')).write_text('archive fixture')
                common = 'echo "$event" >> "$LOG"\n[ "$FAILURE" != "$event" ] || exit 7\n'
                for command, body in {
                    'python3': 'test "$1" = "$GITHUB_WORKSPACE/Scripts/Cache.py"\n'
                               'test "$2" = unpack\n'
                               'test "$4" = "$BUILD"\nevent="$6"\n' + common,
                    'make': 'test "$PWD" = "$BUILD"\ntest "$1" = download\n'
                            'event=download\n' + common,
                }.items():
                    stub = bindir / command
                    stub.write_text('#!/bin/bash -e\n' + body)
                    stub.chmod(0o755)
                code = STEPS['Prepare build inputs']['run'].replace('/mnt/build_wrt', str(root))
                code = code.replace('/mnt/mx4200-cache', str(archives))
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', code], cwd=bindir,
                    env=dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'],
                             GITHUB_WORKSPACE=str(root / 'workspace'), BUILD=str(root),
                             LOG=str(root / 'log'), FAILURE=failure), capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, failure in ('', 'cold'), result.stderr)
                order = ['tc', 'hostpkg', 'rolling', 'download']
                expected = ['download'] if failure == 'cold' else (
                    order[:order.index(failure) + 1] if failure else order)
                self.assertEqual((root / 'log').read_text().splitlines(), expected)
                remaining = sorted(p.name for p in archives.iterdir())
                self.assertEqual(remaining, sorted(t + '.tar.gz' for t in
                    order[order.index(failure):3]) if failure in order[:3] else [])

    def test_images(self):
        for case in ('valid', 'missing', 'empty', 'extra', 'wrong-device'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                images = root / 'bin/targets/qualcommax/ipq807x'
                images.mkdir(parents=True)
                for device in ('mx4200v1', 'mx4200v2'):
                    for kind in ('factory', 'sysupgrade'):
                        if case == 'missing' and (device, kind) == ('mx4200v2', 'factory'):
                            continue
                        name = 'other' if case == 'wrong-device' and device == 'mx4200v2' else device
                        image = images / f'immortalwrt-qualcommax-ipq807x-linksys_{name}-squashfs-{kind}.bin'
                        image.write_bytes(b'' if case == 'empty' else b'fixture, not firmware')
                if case == 'extra':
                    (images / 'other-sysupgrade.bin').write_bytes(b'fixture')
                result = self.run_block('Validate and stage firmware', root)
                self.assertEqual(result.returncode == 0, case == 'valid', result.stdout + result.stderr)

    def test_build_control_flow(self):
        for cold, failure in ((False, ''), (True, ''), (True, 'bootstrap'),
                              (False, 'parallel'), (False, 'final'), (False, 'stats')):
            with self.subTest(cold=cold, failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                bindir = root / 'bin'
                bindir.mkdir()
                host = root / 'staging_dir/host/bin'
                host.mkdir(parents=True)
                counter = root / 'ccache-stub'
                counter.write_text('#!/bin/bash\necho "ccache $*" >> "$LOG"\n[ "$FAILURE" != stats ] || [ "$1" != -s ]\n')
                counter.chmod(0o755)
                if not cold:
                    (host / 'ccache').symlink_to(counter)
                make = bindir / 'make'
                make.write_text('''#!/bin/bash
echo "make $*" >> "$LOG"
if [[ "$*" == *tools/ccache/compile* ]]; then
  [ "$FAILURE" != bootstrap ] || exit 7
  ln -s "$COUNTER" staging_dir/host/bin/ccache
  exit 0
fi
[ "$FAILURE" != final ] || exit 9
if [ "$FAILURE" = parallel ] && [[ "$1" != -j1 ]]; then exit 8; fi
exit 0
''')
                make.chmod(0o755)
                result = self.run_block('Compile firmware', root, {
                    'PATH': str(bindir) + ':' + os.environ['PATH'], 'LOG': str(root / 'log'),
                    'FAILURE': failure, 'COUNTER': str(counter)})
                log = (root / 'log').read_text()
                self.assertEqual(result.returncode == 0, failure in ('', 'parallel', 'stats'), log + result.stderr)
                if failure == 'bootstrap':
                    self.assertEqual(result.returncode, 7)
                    self.assertEqual(len(log.splitlines()), 1)
                    self.assertIn('tools/ccache/compile', log)
                else:
                    calls = log.splitlines()
                    start = 1 if cold else 0
                    self.assertEqual(calls[start], 'ccache -z')
                    self.assertRegex(calls[start + 1], r'^make -j[0-9]+$')
                    expected = calls[:start + 2]
                    if failure in ('parallel', 'final'):
                        expected += ['make -j1 V=s']
                    expected += ['ccache -s']
                    self.assertEqual(calls, expected)
                if failure == 'final':
                    self.assertEqual(result.returncode, 9)
                    self.assertIn('V=s', log)
                    self.assertIn('ccache -s', log)
                if failure == '':
                    self.assertEqual(log.count('ccache -s'), 1)

    def test_release_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upload = root / 'upload'
            upload.mkdir()
            for index in range(4):
                (upload / f'{index}.bin').write_bytes(b'fixture')
            gh = root / 'gh'
            gh.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['LOG'], 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['release', 'list']:
    print(os.environ['WRT_RELEASE_NAME'])
    print('MX4200_old')
    print('Other_keep')
''')
            gh.chmod(0o755)
            result = self.run_block('Publish firmware and prune releases', root, {
                'PATH': str(root) + ':' + os.environ['PATH'], 'LOG': str(root / 'log'),
                'WRT_RELEASE_NAME': 'MX4200_current', 'GITHUB_SHA': 'a' * 40,
                'RELEASE_NOTES': 'fixture notes'})
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in (root / 'log').read_text().splitlines()]
            create = calls[0]
            self.assertEqual(create[create.index('--target') + 1], 'a' * 40)
            self.assertEqual(sum(arg.endswith('.bin') for arg in create), 4)
            deletes = [args for args in calls if args[:2] == ['release', 'delete']]
            self.assertEqual(len(deletes), 1)
            self.assertIn('MX4200_old', deletes[0])


if __name__ == '__main__':
    unittest.main()
