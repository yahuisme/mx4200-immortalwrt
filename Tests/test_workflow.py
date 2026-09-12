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
        code = STEPS[name]['run'].replace('/mnt/build_wrt/', str(root) + '/')
        return subprocess.run(['bash', '-eo', 'pipefail', '-c', code], cwd=root,
                              env=dict(os.environ, **(env or {})), capture_output=True, text=True)

    def test_release_scope(self):
        self.assertEqual(WORKFLOW['concurrency'], {'group': 'mx4200-build', 'cancel-in-progress': False})
        self.assertEqual(STEPS['Release']['if'], "github.ref == 'refs/heads/main'")
        self.assertEqual(WORKFLOW['jobs']['build']['runs-on'], 'ubuntu-24.04')

    def test_cache_contract(self):
        ordered = list(STEPS)
        self.assertLess(ordered.index('Configure'), ordered.index('Cache keys'))
        self.assertLess(ordered.index('Cache keys'), ordered.index('Restore tools'))
        self.assertNotIn('restore-keys', STEPS['Restore tools']['with'])
        self.assertIn('rolling-prefix', STEPS['Restore downloads']['with']['restore-keys'])
        self.assertNotIn('staging_dir', STEPS['Restore tools']['with']['path'])
        for label, tier in (('tools', 'tc'), ('downloads', 'rolling')):
            self.assertLess(ordered.index('Release'), ordered.index('Pack ' + label))
            self.assertLess(ordered.index('Pack ' + label), ordered.index('Save ' + label))
            self.assertLess(ordered.index('Save ' + label), ordered.index('Prune ' + label))
            self.assertIn("github.ref == 'refs/heads/main'", STEPS['Pack ' + label]['if'])
            self.assertIn('admitted', STEPS['Save ' + label]['if'])
            self.assertIn("outcome == 'success'", STEPS['Prune ' + label]['if'])
            self.assertEqual(STEPS['Restore ' + label]['with']['path'],
                             STEPS['Save ' + label]['with']['path'])
        self.assertLess(ordered.index('Prune tools'), ordered.index('Pack downloads'))

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
                result = self.run_block('Images', root)
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
if [ "$FAILURE" = parallel ] && [[ "$*" != *V=s* ]]; then exit 8; fi
staging_dir/host/bin/ccache -s
''')
                make.chmod(0o755)
                result = self.run_block('Build', root, {
                    'PATH': str(bindir) + ':' + os.environ['PATH'], 'LOG': str(root / 'log'),
                    'FAILURE': failure, 'COUNTER': str(counter)})
                log = (root / 'log').read_text()
                self.assertEqual(result.returncode == 0, failure in ('', 'parallel'), log + result.stderr)
                if failure == 'bootstrap':
                    self.assertNotIn('ccache -z', log)
                else:
                    self.assertEqual(log.count('ccache -z'), 1)
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
            result = self.run_block('Release', root, {
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
