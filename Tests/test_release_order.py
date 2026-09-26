"""Replay real workflow order/shell; compiler, Actions save and gh stay local."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml
from Scripts import Cache

ROOT = Path(__file__).resolve().parents[1]
STEPS = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']
PUBLISH = 'Publish firmware and prune releases'
TIERS = ('tc', 'hostpkg', 'rolling')


def eligible(condition, outcomes, outputs, success, cancelled, ref):
    """Subset used by this YAML, including Actions' implicit success() rule."""
    expression = str(condition).removeprefix('${{').removesuffix('}}').strip()
    has_status = re.search(r'\b(success|failure|cancelled|always)\s*\(', expression)
    if not has_status and not (success and not cancelled):
        return False
    expression = expression.replace('success()', repr(success and not cancelled))
    expression = expression.replace('cancelled()', repr(cancelled))
    expression = expression.replace('github.ref', repr(ref))
    expression = re.sub(r'steps\.([\w-]+)\.outcome',
                        lambda m: repr(outcomes.get(m[1], 'skipped')), expression)
    expression = re.sub(r'steps\.([\w-]+)\.outputs\.([\w-]+)',
                        lambda m: repr(outputs.get(m[1], {}).get(m[2], '')), expression)
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', ' not ', expression)
    # Only repository-controlled predicates; no downloaded expressions.
    return bool(eval(expression, {'__builtins__': {}}, {}))


GH_STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
s['calls'].append([os.environ['STEP'], a])
p.write_text(json.dumps(s))
fault, step = os.environ['FAULT'], os.environ['STEP']
if a[:2] == ['release', 'create']:
    assert len([v for v in a if v.endswith('.bin')]) == 4
    sys.exit(9 if fault == 'publish' else 0)
if a[:2] == ['release', 'list']:
    print(os.environ['WRT_RELEASE_NAME'])
    print('MX4200_old')
    print('Other_keep')
elif a[:2] == ['release', 'delete']:
    assert a[-1] == 'MX4200_old'
elif a and a[0] == 'api':
    tier = os.environ['TIER']
    if fault == 'admit-' + tier and step == 'pack-' + tier:
        sys.exit(7)
    if fault == 'prune-' + tier and step.lower().startswith('prune'):
        sys.exit(8)
    if '--method' in a:
        victim = int(a[-1].split('/')[-1])
        s['rows'] = [r for r in s['rows'] if r['id'] != victim]
    else:
        print(json.dumps([{'actions_caches': s['rows']}]))
else:
    raise SystemExit('unexpected gh call: ' + repr(a))
p.write_text(json.dumps(s))
'''


class ReleaseOrderTests(unittest.TestCase):
    def replay(self, fault='none', ref='refs/heads/main'):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            build, archives, bindir = (base / p for p in ('build', 'archives', 'bin'))
            for p in (build, archives, bindir):
                p.mkdir()
            for name in ('build_dir/host', 'staging_dir/host/bin', 'build_dir/toolchain-fixture',
                         'staging_dir/toolchain-fixture', 'build_dir/hostpkg',
                         'staging_dir/hostpkg', 'dl', '.ccache'):
                p = build / name
                p.mkdir(parents=True, exist_ok=True)
                (p / 'payload').write_text('cache fixture')
            images = build / 'bin/targets/qualcommax/ipq807x'
            images.mkdir(parents=True)
            for device in ('mx4200v1', 'mx4200v2'):
                for kind in ('factory', 'sysupgrade'):
                    (images / f'immortalwrt-linksys_{device}-squashfs-{kind}.bin').write_bytes(
                        b'' if fault == 'stage' else b'image fixture, not firmware')
            stubs = {
                bindir / 'gh': GH_STUB,
                bindir / 'make': '#!/bin/bash\n[ "$CCACHE_MAXSIZE" = 2G ] || exit 91\n'
                                 '[ "$FAULT" != compile ] || exit 7\n',
                build / 'staging_dir/host/bin/ccache': '#!/bin/bash\n[ "$CCACHE_MAXSIZE" = 2G ]\n',
            }
            for path, text in stubs.items():
                path.write_text(text)
                path.chmod(0o755)
            prefix = Cache.scope(ref)
            state = base / 'state.json'
            old = [dict(id=i, key=prefix + tier + '-old', ref=ref, size_in_bytes=1,
                        created_at='2026-01-01') for i, tier in enumerate(TIERS, 1)]
            state.write_text(json.dumps({'rows': old, 'calls': []}))
            env = dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'],
                       STATE=str(state), FAULT=fault, GITHUB_REF=ref,
                       GITHUB_REPOSITORY='fixture/repo', GITHUB_SHA='a' * 40,
                       WRT_RELEASE_NAME='MX4200_fixture', WRT_RELEASE_TITLE='fixture title',
                       GH_TOKEN='fixture-token-not-a-credential')
            outcomes, outputs, trace, diagnostics = {}, {
                'tools': {'cache-hit': 'false'}, 'hostpkg': {'cache-hit': 'false'},
                'keys': {'tc-key': prefix + 'tc-new'},
                'hostpkg-key': {'hostpkg-key': prefix + 'hostpkg-new'},
                'rolling': {'cache-primary-key': prefix + 'rolling-new'},
            }, [], []
            success, cancelled = True, fault == 'cancel-before-compile'
            start = next(i for i, s in enumerate(STEPS) if s['name'] == 'Compile firmware')
            for step in STEPS[start:]:
                ident = step.get('id', step['name'])
                if not eligible(step.get('if', 'True'), outcomes, outputs, success, cancelled, ref):
                    outcomes[ident] = 'skipped'
                    trace.append((ident, 'skipped'))
                    continue
                tier = ('hostpkg' if 'hostpkg' in step['name'] else
                        'rolling' if 'downloads' in step['name'] else 'tc')
                output = base / 'output'
                output.write_text('')
                env.update(STEP=ident, TIER=tier, GITHUB_OUTPUT=str(output))
                for key, value in step.get('env', {}).items():
                    env[key] = re.sub(r'\$\{\{ steps\.([\w-]+)\.outputs\.([\w-]+) \}\}',
                                      lambda m: outputs[m[1]][m[2]], value)
                if 'uses' in step:
                    self.assertEqual(step['uses'], 'actions/cache/save@main')
                    rc = 7 if fault == 'save-' + tier else 0
                    if not rc and fault != 'unconfirmed-' + tier:
                        saved = json.loads(state.read_text())
                        saved['rows'].append(dict(id=10 + TIERS.index(tier), key=prefix + tier + '-new',
                                                  ref=ref, size_in_bytes=(archives / (tier + '.tar.gz')).stat().st_size,
                                                  created_at='2026-09-26'))
                        state.write_text(json.dumps(saved))
                else:
                    if ident == 'pack-' + tier and fault == 'pack-' + tier:
                        shutil.rmtree(build / {'tc': 'build_dir/host',
                                              'hostpkg': 'build_dir/hostpkg', 'rolling': 'dl'}[tier])
                    code = step['run'].replace('/mnt/build_wrt', str(build))
                    code = code.replace('/mnt/mx4200-cache', str(archives))
                    code = code.replace('python3 Scripts/Cache.py', f'{sys.executable} {ROOT}/Scripts/Cache.py')
                    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', code],
                                            cwd=ROOT, env=env, capture_output=True, text=True)
                    rc = result.returncode
                    diagnostics.append((ident, result.stdout, result.stderr))
                    outputs[ident] = dict(line.split('=', 1) for line in output.read_text().splitlines())
                outcomes[ident] = 'success' if rc == 0 else 'failure'
                trace.append((ident, outcomes[ident]))
                if rc and not step.get('continue-on-error', False):
                    success = False
                if step['name'] == 'Validate and stage firmware' and fault == 'cancel-after-stage':
                    cancelled = True
                if step['name'] == 'Prune old downloads and ccache' and fault == 'cancel-after-cache':
                    cancelled = True
            return outcomes, trace, json.loads(state.read_text()), success, diagnostics

    def test_publish_failure_does_not_discard_confirmed_caches(self):
        outcomes, trace, state, success, diagnostics = self.replay('publish')
        self.assertFalse(success)
        self.assertEqual(outcomes[PUBLISH], 'failure')
        self.assertEqual({r['id'] for r in state['rows']}, {10, 11, 12}, diagnostics)
        self.assertEqual(trace[-1], (PUBLISH, 'failure'))
        self.assertFalse(any(a[:2] == ['release', 'delete'] for _, a in state['calls']))

    def test_failure_matrix(self):
        faults = ['none', 'compile', 'stage', 'cancel-before-compile', 'cancel-after-stage',
                  'cancel-after-cache'] + [f'{kind}-{tier}' for tier in TIERS
                  for kind in ('pack', 'admit', 'save', 'prune', 'unconfirmed')]
        for fault in faults:
            with self.subTest(fault=fault):
                outcomes, trace, state, success, diagnostics = self.replay(fault)
                blocked = fault in ('compile', 'stage') or fault.startswith('cancel-')
                self.assertEqual(outcomes[PUBLISH], 'skipped' if blocked else 'success', diagnostics)
                if blocked:
                    self.assertFalse(any(a[0] == 'release' for _, a in state['calls']))
                else:
                    self.assertTrue(success, diagnostics)
                    self.assertEqual(trace[-1], (PUBLISH, 'success'))
                if fault == 'none':
                    self.assertTrue(all(result == 'success' for _, result in trace), trace)
                    self.assertEqual({r['id'] for r in state['rows']}, {10, 11, 12})
                elif '-' in fault and fault.split('-', 1)[1] in TIERS:
                    kind, tier = fault.split('-', 1)
                    failed = ('prune' if kind == 'unconfirmed' else
                              'pack' if kind == 'admit' else kind)
                    name = f'{failed}-{tier}'
                    if name == 'prune-rolling':
                        name = 'Prune old downloads and ccache'
                    self.assertEqual(outcomes[name], 'failure', diagnostics)
                    self.assertIn(1 + TIERS.index(tier), {r['id'] for r in state['rows']})
                    if kind in ('save', 'prune', 'unconfirmed'):
                        for following in TIERS[TIERS.index(tier) + 1:]:
                            self.assertEqual(outcomes['pack-' + following], 'skipped')
                if fault in ('compile', 'stage', 'cancel-before-compile', 'cancel-after-stage'):
                    self.assertEqual(state['calls'], [])

    def test_nonmain_has_no_release_or_cache_writes(self):
        outcomes, _, state, success, _ = self.replay(ref='refs/heads/topic')
        self.assertTrue(success)
        self.assertEqual(outcomes[PUBLISH], 'skipped')
        self.assertEqual(state['calls'], [])

    def test_publish_condition_has_no_implicit_success_dependency(self):
        condition = next(s['if'] for s in STEPS if s['name'] == PUBLISH)
        self.assertFalse(eligible("steps.stage.outcome == 'success'", {'stage': 'success'},
                                  {}, False, False, 'refs/heads/main'))
        for stage in ('success', 'failure', 'skipped'):
            for cancelled in (False, True):
                for success in (False, True):
                    with self.subTest(stage=stage, cancelled=cancelled, success=success):
                        self.assertEqual(eligible(condition, {'stage': stage}, {}, success,
                                                  cancelled, 'refs/heads/main'),
                                         stage == 'success' and not cancelled)


if __name__ == '__main__':
    unittest.main()
