"""Per-step failure and cancellation replay of the actual publication tail."""
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import STEPS, step, render, render_env
import test_release_safety as release
from test_cache_workflow import ROOT
from test_cache_helper import GH, entry
from test_record_collection import prepare
READBACK = """
    assets=[dict(name=p.name,size=p.stat().st_size,state='uploaded',digest='sha256:'+__import__('hashlib').sha256(p.read_bytes()).hexdigest()) for p in Path('firmware').glob('*.bin')]
    print(json.dumps(dict(tag_name=Path('firmware/version.txt').read_text().strip(),draft=False,prerelease=False,assets=assets)))
"""

class CachePublicationIntegrationTests(unittest.TestCase):
    def test_stage_status_gate_after_complete_cache_tail(self):
        publish = step('Publish firmware and prune releases')
        self.assertEqual(step('Validate and stage firmware').get('id'), 'stage')
        self.assertEqual(publish.get('if'), "${{ !cancelled() && github.ref == 'refs/heads/main' && steps.stage.outcome == 'success' }}")
        self.assertEqual(publish['env'], {'GH_TOKEN': '${{ secrets.RELEASE_TOKEN }}'})
        self.assertEqual(STEPS[-1], publish)
        self.assertLess(STEPS.index(step('Prune old download caches')), STEPS.index(publish))
        for item in STEPS[STEPS.index(step('Prepare build caches')):STEPS.index(step('Prune old download caches')) + 1]:
            self.assertNotRegex(item.get('if', ''), r'\b(always|failure|cancelled)\(')
            self.assertFalse(item.get('continue-on-error', False))

    def replay(self, fault, tc_hit='false', tb_hit='false'):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            release.ReleaseTests().fixture(base)
            (base / "bin").symlink_to(base / "openwrt_bin")
            prepare(base)
            if fault == 'metadata':
                (base / '.custom-revisions.tsv').unlink()
            if fault == 'validation':
                (base / '.config').write_text('CONFIG_TARGET_wrong=y\n')
            cc = base / 'staging_dir/host/bin/ccache'
            cc.parent.mkdir(parents=True)
            cc.write_text('#!/bin/sh\nexit 0\n')
            cc.chmod(0o755)
            for directory in ('ccarchive', 'tcarchive', 'dlarchive', 'dlcache', 'tbarchive'):
                (base / directory).mkdir()
            state = base / 'state.json'
            old = [entry(1, 'cc-v1-mx4200-arm64.old'), entry(2, 'tc-v1-mx4200-arm64-old'), entry(3, 'dl-v1-mx4200-arm64.old')]
            state.write_text(json.dumps(dict(entries=old, calls=[], reads=0,
                                             fail_reads=[2] if fault == 'readback' else [8] if fault == 'bootstrap_readback' else [])))
            gh = GH.replace("if a == ['api', '--paginate'", """if a[:2] == ['api', 'repos/fixture/repo/git/ref/heads/main']:
    p.write_text(json.dumps(s)); print(os.environ['GITHUB_SHA']); sys.exit(0)
elif a[0] == 'api' and '/releases/tags/' in a[1]:
    p.write_text(json.dumps(s))
""" + READBACK + """
    sys.exit(0)
elif a[:2] == ['release', 'create']:
    p.write_text(json.dumps(s)); sys.exit(19 if os.environ['FAULT']=='publish' else 0)
elif a == ['api', '--paginate', '--slurp', 'repos/fixture/repo/releases?per_page=100']:
    p.write_text(json.dumps(s)); print('[[]]'); sys.exit(0)
elif a[:2] == ['release', 'delete']:
    p.write_text(json.dumps(s)); sys.exit(0)
elif a == ['api', '--paginate'""")
            (base / 'gh').write_text(gh)
            (base / 'gh').chmod(0o755)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       MOCK_STATE=str(state), GITHUB_REF='refs/heads/main',
                       GITHUB_SHA='a'*40, GITHUB_REPOSITORY='fixture/repo',
                       GITHUB_OUTPUT=str(base / 'output'), RUNNER_TEMP=tmp,
                       DK_OPENWRT=tmp, FAULT=fault, IMAGE_ID='sha256:'+'a'*64, BUILDER_FINGERPRINT='b'*64)
            # Real nested compile shell and stage; compiler, Docker and archive
            # compressor are external boundaries. No firmware build/network occurs.
            prefix = '''
make() { printf 'make %s\n' "$*" >> "$RUNNER_TEMP/bootstrap-calls"; [ "$FAULT" != compile ]; }
python3() {
    if [ "$1" = /cache-scripts/bootstrap_cache.py ]; then
        printf 'bootstrap pack\n' >> "$RUNNER_TEMP/bootstrap-calls"
        [ "$FAULT" != bootstrap_pack ] || return 29
        truncate -s 100 tbarchive/bootstrap.tar.gz
    else
        command python3 "$@"
    fi
}
docker_exec() {
    shift
    if [ "$1" = python3 ] && [ "$2" = /cache-scripts/build_record.py ]; then
        python3 scripts/build_record.py "$DK_OPENWRT" build-record
    elif [ "$1" = python3 ] && [ "$2" = /cache-scripts/cache.py ]; then
        [ "$FAULT" != package ] || return 17
        mkdir -p "${5#/}"
        truncate -s 100 "${5#/}/$3.tar.gz"
    else
        "$@"
    fi
}
sudo() { "$@"; }
export -f make docker_exec sudo python3
'''
            subprocess.run(['python3', str(ROOT/'scripts/dlcache.py'), 'snapshot',
                            str(base/'dlcache'), str(base/'dlcache-before.json')], check=True,
                           capture_output=True)
            (base/'dlcache/new-download').write_bytes(b'fixture download')
            values = {'steps.tc.outputs.cache-hit': tc_hit,
                      'steps.tb.outputs.cache-hit': tb_hit,
                      'steps.tb_inputs.outputs.key': 'tb-v1-mx4200-arm64-new',
                      'secrets.RELEASE_TOKEN': 'fixture-token',
                      'steps.inputs.outputs.key': 'tc-v1-mx4200-arm64-new',
                      'steps.gh.outputs.cache-primary-key': 'cc-v1-mx4200-arm64.new',
                      'steps.dl.outputs.cache-primary-key': 'dl-v1-mx4200-arm64.new',
                      'steps.dl.outputs.cache-matched-key': '',
                      'steps.stage.outcome': 'skipped'}
            successful, cancelled = True, False
            outcomes, executed, logs = {}, [], []
            def condition(expr):
                expression = expr.removeprefix('${{').removesuffix('}}').strip()
                status = re.search(r'\b(success|failure|cancelled|always)\(', expression)
                if not status and (not successful or cancelled):
                    return False  # Actions implicit success(), not just expression truth.
                for token, value in [('!cancelled()', not cancelled), ('cancelled()', cancelled),
                                     ('success()', successful), ('failure()', not successful), ('always()', True)]:
                    expression = expression.replace(token, repr(value))
                expression = re.sub(r"hashFiles\('([^']+)'\)",
                                    lambda m: repr('present' if (base/m[1]).exists() else ''), expression)
                expression = expression.replace('github.ref', repr('refs/heads/main'))
                expression = re.sub(r'steps\.[\w.-]+', lambda m: repr(values.get(m[0], '')), expression)
                # Only trusted repository comparisons and repr-quoted local
                # fixture values are evaluated, never external/event input.
                return eval(expression.replace('&&', ' and '), {'__builtins__': {}})
            for item in STEPS[STEPS.index(step('Compile firmware')):]:
                name = item['name']
                if fault == 'cancel' and name == 'Prepare build caches':
                    cancelled = True
                if not condition(item.get('if', 'True')):
                    outcomes[name] = 'skipped'
                    continue
                executed.append(name)
                if 'run' in item:
                    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', prefix + render(item['run'], values)],
                                            cwd=base, env=dict(env, **render_env(item, values)), text=True, capture_output=True)
                    rc = result.returncode
                    logs.append(name + '\n' + result.stdout + result.stderr)
                else:
                    self.assertIn(item['uses'], ('actions/cache/save@v6', 'actions/upload-artifact@v7'))
                    rc = 23 if ((fault == 'save' and item['uses'] == 'actions/cache/save@v6') or
                                   (fault == 'bootstrap_save' and item.get('with', {}).get('path') == 'tbarchive') or
                                   (fault == 'upload' and item['uses'] == 'actions/upload-artifact@v7')) else 0
                    if not rc and item['uses'] == 'actions/cache/save@v6':
                        inventory = json.loads(state.read_text())
                        inventory['entries'].append(entry(100+len(executed), render(item['with']['key'], values)))
                        state.write_text(json.dumps(inventory))
                outcome = 'success' if rc == 0 else 'failure'
                outcomes[name] = outcome
                if item.get('id'):
                    values[f"steps.{item['id']}.outcome"] = outcome
                    output = base/'output'
                    if output.exists():
                        for line in output.read_text().splitlines():
                            k, v = line.split('=', 1)
                            values[f"steps.{item['id']}.outputs.{k}"] = v
                        output.unlink()
                successful = successful and rc == 0
            calls = (base / 'bootstrap-calls').read_text() if (base / 'bootstrap-calls').exists() else ''
            return outcomes, executed, json.loads(state.read_text()), '\n'.join(logs) + '\n' + calls

    def test_compile_cache_state_branches_use_production_env(self):
        for tc, tb, want_make, want_pack in (('false', 'false', True, True),
                                             ('false', 'true', True, False),
                                             ('true', '', False, False)):
            with self.subTest(tc=tc, tb=tb):
                outcomes, _, _, log = self.replay('none', tc_hit=tc, tb_hit=tb)
                calls = [line for line in log.splitlines() if line.startswith('make ')]
                self.assertEqual(any(line.startswith('make tools/ccache/compile') for line in calls), want_make, log)
                self.assertEqual('bootstrap pack' in log, want_pack, log)
                self.assertEqual(outcomes['Publish firmware and prune releases'], 'success', log)

    def test_full_compile_stage_cache_publish_failure_matrix(self):
        for fault in ('none', 'compile', 'validation', 'cancel', 'package', 'save', 'readback', 'publish', 'metadata', 'upload', 'bootstrap_pack', 'bootstrap_save', 'bootstrap_readback'):
            with self.subTest(fault=fault):
                outcomes, executed, inventory, log = self.replay(fault)
                published = fault not in ('compile', 'validation', 'cancel')
                creates = [call for call in inventory['calls'] if call[:2] == ['release', 'create']]
                self.assertEqual(bool(creates), published, log)
                self.assertEqual(outcomes['Publish firmware and prune releases'],
                                 'failure' if fault == 'publish' else 'success' if published else 'skipped', log)
                if fault in ('none', 'publish', 'metadata', 'upload'):
                    self.assertEqual({item['key'] for item in inventory['entries']},
                                     {'cc-v1-mx4200-arm64.new', 'tc-v1-mx4200-arm64-new',
                                      'tb-v1-mx4200-arm64-new', 'dl-v1-mx4200-arm64.new'}, log)
                    self.assertLess(executed.index('Prune old download caches'),
                                    executed.index('Publish firmware and prune releases'))
                elif fault == 'bootstrap_pack':
                    self.assertEqual({item['key'] for item in inventory['entries']},
                                     {'cc-v1-mx4200-arm64.new', 'tc-v1-mx4200-arm64-new',
                                      'dl-v1-mx4200-arm64.new'}, log)
                    self.assertEqual(outcomes['Check bootstrap cache budget'], 'skipped', log)
                elif fault in ('bootstrap_save', 'bootstrap_readback'):
                    self.assertEqual(outcomes['Check download cache budget'], 'skipped', log)
                    self.assertIn(3, {item['id'] for item in inventory['entries']}, log)
                    self.assertEqual(outcomes['Publish firmware and prune releases'], 'success', log)
                else:
                    self.assertTrue({1, 2, 3} <= {item['id'] for item in inventory['entries']}, log)
                if fault in ('save', 'readback'):
                    self.assertEqual(outcomes['Check toolchain cache budget'], 'skipped', log)
