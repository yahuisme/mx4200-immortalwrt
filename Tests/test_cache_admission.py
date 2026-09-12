"""Local native compression and mocked read-only GitHub API tests."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'Scripts' / 'CacheAdmission.py'
spec = importlib.util.spec_from_file_location('cache_admission', SCRIPT)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


def entry(ident=1, size=100, key='old', ref='refs/heads/main'):
    return dict(id=ident, size_in_bytes=size, key=key, ref=ref)


def response(entries, total=None):
    return subprocess.CompletedProcess([], 0, json.dumps({
        'total_count': len(entries) if total is None else total,
        'actions_caches': entries}))


class AdmissionTests(unittest.TestCase):
    def test_pagination_counts_all_refs_and_legacy_without_mutations(self):
        first = [entry(i, 90_000_000, key=f'legacy-{i}', ref='refs/heads/other') for i in range(1, 101)]
        with patch.object(cache.subprocess, 'run', side_effect=[response(first, 101), response([entry(101, 490_000_000)], 101)]) as run:
            result = cache.admit('owner/repo', 'new', 'refs/heads/main', 490_000_000)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['used_bytes'], 9_490_000_000)
        self.assertEqual(result['reserve_bytes'], 16 * 1024 * 1024)
        for index, call in enumerate(run.call_args_list, 1):
            self.assertEqual(call.args[0], ['gh', 'api', '--method', 'GET',
                             f'repos/owner/repo/actions/caches?per_page=100&page={index}'])

    def test_realistic_headroom_rejects_large_candidate(self):
        with patch.object(cache, 'inventory', return_value=[entry(size=9_490_000_000)]):
            result = cache.admit('o/r', 'new', 'refs/heads/main', 500_000_000)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['reason'], 'insufficient headroom')

    def test_reserve_rounding_boundary_and_fresh_inventory(self):
        candidate = 2_000_000_001
        reserve = 20_000_001
        budget = candidate + reserve
        with patch.object(cache, 'inventory', side_effect=[[], [entry(size=1)]]) as read:
            first = cache.admit('o/r', 'new', 'refs/heads/main', candidate, budget)
            second = cache.admit('o/r', 'next', 'refs/heads/main', candidate, budget)
        self.assertEqual(first['reserve_bytes'], reserve)
        self.assertTrue(first['allowed'])
        self.assertFalse(second['allowed'])
        self.assertEqual(read.call_count, 2)

    def test_existing_exact_key_disallows_overwrite(self):
        with patch.object(cache, 'inventory', return_value=[entry(key='new')]):
            self.assertFalse(cache.admit('o/r', 'new', 'refs/heads/main', 10)['allowed'])

    def test_verify_requires_exact_nonempty_current_ref(self):
        cases = [[], [entry(key='new-prefix')], [entry(key='new', size=0)],
                 [entry(key='new', ref='refs/heads/other')], [entry(key='new')]]
        for entries in cases:
            with self.subTest(entries=entries), patch.object(cache, 'inventory', return_value=entries):
                result = cache.verify('o/r', 'new', 'refs/heads/main')
                self.assertEqual(result['verified'], entries == cases[-1])

    def test_api_failures_fail_closed(self):
        failures = [FileNotFoundError('gh'), subprocess.TimeoutExpired('gh', 60),
                    subprocess.CalledProcessError(1, 'gh'),
                    subprocess.CompletedProcess([], 0, 'not json'),
                    response([entry(size=-1)]), response([entry()], total=2),
                    response([entry(), entry()]),
                    subprocess.CompletedProcess([], 0, '{"total_count": true, "actions_caches": []}')]
        for failure in failures:
            kwargs = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
            with self.subTest(failure=failure), patch.object(cache.subprocess, 'run', **kwargs):
                self.assertFalse(cache.admit('o/r', 'new', 'refs/heads/main', 10)['allowed'])
                self.assertFalse(cache.verify('o/r', 'new', 'refs/heads/main')['verified'])

    def test_second_page_failure_and_drift(self):
        first = [entry(i) for i in range(1, 101)]
        for last in [subprocess.CalledProcessError(1, 'gh'), response([entry(101)], 102)]:
            with patch.object(cache.subprocess, 'run', side_effect=[response(first, 101), last]):
                self.assertFalse(cache.admit('o/r', 'new', 'refs/heads/main', 10)['allowed'])

    def test_invalid_config_is_not_suppressed(self):
        with patch.object(cache, 'inventory') as read:
            for repo, key, ref, size, budget in [('bad', 'new', 'refs/heads/main', 1, cache.BUDGET),
                    ('o/r', '', 'refs/heads/main', 1, cache.BUDGET),
                    ('o/r', 'new', 'main', 1, cache.BUDGET),
                    ('o/r', 'new', 'refs/heads/main', 0, cache.BUDGET),
                    ('o/r', 'new', 'refs/heads/main', 1, cache.BUDGET + 1)]:
                with self.assertRaises(ValueError):
                    cache.admit(repo, key, ref, size, budget)
            read.assert_not_called()

    def test_cli_api_unavailable_exit_zero_and_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'outputs'
            env = {**os.environ, 'PATH': temp, 'GITHUB_OUTPUT': str(output)}
            for command, field in [('admit', 'allowed'), ('verify', 'verified')]:
                args = [sys.executable, str(SCRIPT), command, '--repo', 'o/r',
                        '--key', 'new', '--ref', 'refs/heads/main']
                if command == 'admit':
                    args += ['--bytes', '100']
                result = subprocess.run(args, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(json.loads(result.stdout)[field])
                self.assertIn(f'{field}=false\n', output.read_text())
            bad = subprocess.run([sys.executable, str(SCRIPT), 'measure', 'dl', temp],
                                 env=env, capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)


@unittest.skipUnless(shutil.which('tar') and shutil.which('zstd'), 'requires native tar and zstd')
class MeasurementTests(unittest.TestCase):
    def test_real_pax_zstd_all_native_tiers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dirs = ['dl', '.ccache', 'staging_dir/host', 'staging_dir/toolchain-test',
                    'build_dir/host', 'build_dir/toolchain-test']
            for name in dirs:
                path = root / name
                path.mkdir(parents=True)
                sample = path / 'sample'
                sample.write_bytes(b'native cache sample\n' * 10000)
                os.utime(sample, ns=(1700000000123456789, 1700000000123456789))
                (path / 'link').symlink_to('sample')
            excluded = root / 'build_dir/hostpkg'
            excluded.mkdir()
            (excluded / 'not-cached').write_bytes(os.urandom(10000))
            for tier in ('dl', 'ccache', 'tools'):
                with self.subTest(tier=tier):
                    paths = cache.native_paths(root, tier)
                    before = {str(p): p.stat().st_mtime_ns for d in paths for p in d.iterdir()}
                    measured = cache.measure(root, tier)
                    manifest = b''.join(os.fsencode(p) + b'\0' for p in paths)
                    tar = subprocess.run(['tar', '--posix', '-P', '-cf', '-', '--null',
                                          '--verbatim-files-from', '-T', '-'], input=manifest,
                                         capture_output=True, check=True)
                    compressed = subprocess.run(['zstd', '-T0', '--long=30', '-c'], input=tar.stdout,
                                                capture_output=True, check=True).stdout
                    # PAX atime can change on reads; admission reserve covers that tiny variance.
                    self.assertLess(abs(measured - len(compressed)), 1024)
                    self.assertLess(measured, sum((p / 'sample').stat().st_size for p in paths))
                    archive = root / 'sample.tar'
                    archive.write_bytes(subprocess.run(['zstd', '-d', '--long=30', '-c'], input=compressed,
                                                       capture_output=True, check=True).stdout)
                    with tarfile.open(archive) as opened:
                        members = opened.getmembers()
                        self.assertFalse(any('hostpkg' in member.name for member in members))
                        self.assertEqual(sum(member.issym() for member in members), len(paths))
                        for member in members:
                            if member.name.endswith('/sample'):
                                self.assertEqual(member.pax_headers['mtime'], '1700000000.123456789')
                    self.assertEqual(before, {str(p): p.stat().st_mtime_ns for d in paths for p in d.iterdir()})
            cli = subprocess.run([sys.executable, str(SCRIPT), 'measure', 'dl', temp],
                                 env={k: v for k, v in os.environ.items() if k != 'GITHUB_OUTPUT'},
                                 capture_output=True, text=True, check=True)
            self.assertGreater(json.loads(cli.stdout)['candidate_bytes'], 0)

    def test_hostpkg_stat_only(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'hostpkg.tar.zst'
            data = subprocess.run(['zstd', '-c'], input=b'hostpkg data' * 1000,
                                  capture_output=True, check=True).stdout
            archive.write_bytes(data)
            with patch.object(cache.subprocess, 'Popen') as process:
                self.assertEqual(cache.measure(temp, 'hostpkg'), len(data))
                process.assert_not_called()

    def test_missing_empty_and_unmatched_paths_raise(self):
        with tempfile.TemporaryDirectory() as temp:
            for tier in ('dl', 'ccache', 'tools', 'hostpkg'):
                with self.assertRaises(ValueError):
                    cache.measure(temp, tier)
            (Path(temp) / 'hostpkg.tar.zst').touch()
            with self.assertRaises(ValueError):
                cache.measure(temp, 'hostpkg')
            (Path(temp) / 'dl').symlink_to(temp, target_is_directory=True)
            with self.assertRaises(ValueError):
                cache.measure(temp, 'dl')

    def test_compression_error_propagates(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'dl').mkdir()
            real = subprocess.Popen
            def popen(args, **kwargs):
                if args[0] == 'zstd':
                    args = ['zstd', '--not-an-option']
                return real(args, **kwargs)
            with patch.object(cache.subprocess, 'Popen', side_effect=popen):
                with self.assertRaises(RuntimeError):
                    cache.measure(temp, 'dl')


@unittest.skipUnless(shutil.which('tar') and shutil.which('zstd'), 'requires native tar and zstd')
class WorkflowTests(unittest.TestCase):
    """Execute real YAML shell blocks; emulate only Actions gates/save and gh reads."""

    @classmethod
    def setUpClass(cls):
        import yaml
        cls.root = SCRIPT.parents[1]
        workflow = yaml.safe_load((cls.root / '.github/workflows/MX4200.yml').read_text())
        cls.steps = workflow['jobs']['build']['steps']
        cls.by_id = {s['id']: s for s in cls.steps if 'id' in s}

    def gate(self, expression, states, environment, success=True):
        import re
        expression = expression.replace('success()', repr(success))
        expression = re.sub(r'steps\.([\w-]+)\.(outputs\.[\w-]+|outcome)',
                            lambda m: repr(states.get(m[1], {}).get(m[2], '')), expression)
        expression = re.sub(r'env\.([\w_]+)', lambda m: repr(environment.get(m[1], '')), expression)
        # Only trusted repository YAML is evaluated; substituted values use repr.
        return eval(expression.replace('&&', ' and ').replace('||', ' or '), {'__builtins__': {}})

    def test_measurement_gates(self):
        states = {'downloads-after': {'outputs.files': '1', 'outputs.digest': 'same'},
                  'downloads-before': {'outputs.digest': 'same'},
                  'downloads': {'outputs.cache-matched-key': 'split'},
                  'cache-selection': {'outputs.legacy-downloads': 'false'}}
        for ident in ('toolchain', 'downloads', 'ccache', 'hostpkg'):
            step = self.by_id[ident + '-admission']
            self.assertFalse(self.gate(step['if'], states, {}, success=False))
            self.assertFalse(self.gate(step['if'], states, {'CACHE_SAVES_BLOCKED': 'true'}))
            self.assertTrue(step['continue-on-error'])
        dl = self.by_id['downloads-admission']['if']
        self.assertFalse(self.gate(dl, states, {}), 'unchanged split must not even measure')
        states['downloads-after']['outputs.digest'] = 'changed'
        self.assertTrue(self.gate(dl, states, {}))
        states['downloads-after']['outputs.files'] = '0'
        self.assertFalse(self.gate(dl, states, {}))
        states['downloads-after'].update({'outputs.files': '1', 'outputs.digest': 'same'})
        states['downloads']['outputs.cache-matched-key'] = ''
        self.assertTrue(self.gate(dl, states, {}), 'seed missing split')
        states['downloads']['outputs.cache-matched-key'] = 'split'
        states['cache-selection']['outputs.legacy-downloads'] = 'true'
        self.assertTrue(self.gate(dl, states, {}), 'newer combined must seed split')
        for ident in ('toolchain', 'hostpkg'):
            states[ident] = {'outputs.cache-hit': 'true'}
            self.assertFalse(self.gate(self.by_id[ident + '-admission']['if'], states, {}))

    def test_all_saves_use_same_identity_and_confirm_before_next_tier(self):
        saves = [s for s in self.steps if s.get('uses', '').startswith('actions/cache/save@')]
        self.assertEqual([s['id'] for s in saves], ['save-toolchain', 'save-downloads', 'save-ccache', 'save-hostpkg'])
        for index, step in enumerate(saves):
            ident = step['id'].removeprefix('save-')
            admit = self.by_id[ident + '-admission']
            verify = self.by_id['verify-' + ident]
            self.assertEqual(admit['env']['CACHE_KEY'], step['with']['key'])
            self.assertEqual(verify['env']['CACHE_KEY'], step['with']['key'])
            self.assertIn('--ref "$GITHUB_REF"', admit['run'])
            self.assertIn('--ref "$GITHUB_REF"', verify['run'])
            self.assertTrue(step['continue-on-error'])
            self.assertTrue(verify['continue-on-error'])
            self.assertLess(self.steps.index(admit), self.steps.index(step))
            self.assertLess(self.steps.index(step), self.steps.index(verify))
            if index + 1 < len(saves):
                next_id = saves[index + 1]['id'].removeprefix('save-')
                self.assertLess(self.steps.index(verify), self.steps.index(self.by_id[next_id + '-admission']))
        self.assertNotIn('HostpkgCache.py admit', '\n'.join(s.get('run', '') for s in self.steps))
        release = next(s for s in self.steps if s.get('name') == 'Release firmware')
        self.assertNotIn('CACHE_SAVES_BLOCKED', release['if'])
        # Preserve exact-cache path identity: restores and saves must stay paired.
        for ident in ('toolchain', 'hostpkg'):
            self.assertEqual(self.by_id[ident]['with']['path'], self.by_id['save-' + ident]['with']['path'])

    def test_execute_admission_save_readback_sequence(self):
        # A failed/warning-only action, API failure, and broken verification all
        # fail closed for later saves but retain success() for image/release work.
        cases = [('confirmed', None), ('denied', None), ('measure-failure', None)]
        cases += [(mode, tier) for mode in ('unconfirmed', 'action-failure', 'api-failure', 'verify-failure')
                  for tier in ('toolchain', 'downloads', 'ccache', 'hostpkg')]
        for mode, affected in cases:
            with self.subTest(mode=mode, tier=affected), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                build = root / 'build'
                for path in ('dl', '.ccache', 'staging_dir/host', 'staging_dir/toolchain-test',
                             'build_dir/host', 'build_dir/toolchain-test'):
                    directory = build / path
                    directory.mkdir(parents=True)
                    (directory / 'sample').write_bytes(b'cache fixture' * 100)
                if mode == 'denied':
                    (build / 'staging_dir/host/sample').write_bytes(os.urandom(100_000))
                if mode == 'measure-failure':
                    (build / 'staging_dir/host').rename(build / 'missing-host')
                bin_dir = root / 'bin'
                bin_dir.mkdir()
                gh = bin_dir / 'gh'
                gh.write_text('#!/usr/bin/env python3\nimport os\nfrom pathlib import Path\nprint(Path(os.environ["INVENTORY"]).read_text())\n')
                gh.chmod(0o755)
                inv = root / 'inventory.json'
                remote = [entry(size=cache.BUDGET - cache.MIN_RESERVE - 50_000)] if mode == 'denied' else []
                env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
                       'INVENTORY': str(inv), 'GITHUB_OUTPUT': str(root / 'output'),
                       'GITHUB_ENV': str(root / 'env'), 'RUNNER_TEMP': tmp,
                       'GITHUB_REPOSITORY': 'o/r', 'GITHUB_REF': 'refs/heads/main'}
                states = {'downloads-after': {'outputs.files': '1'}}
                saved = []

                def run(step, key):
                    inv.write_text(json.dumps({'total_count': len(remote), 'actions_caches': remote}))
                    Path(env['GITHUB_OUTPUT']).write_text('')
                    Path(env['GITHUB_ENV']).write_text('')
                    code = step['run'].replace('/mnt/build_wrt', str(build))
                    # Hostpkg packing has its own roundtrip tests. Isolate that
                    # producer here; measurement still stats the actual archive.
                    code = code.replace('python3 Scripts/HostpkgCache.py pack ' + str(build) + ' ' + str(build / 'hostpkg.tar.zst'),
                                        'printf hostpkg-fixture > ' + str(build / 'hostpkg.tar.zst'))
                    if mode == 'api-failure' and step['id'] == 'verify-' + str(affected):
                        inv.write_text('unavailable')
                    if mode == 'verify-failure' and step['id'] == 'verify-' + str(affected):
                        code = code.replace('python3 Scripts/CacheAdmission.py verify', 'false verify')
                    result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', code],
                                            cwd=self.root, env={**env, 'CACHE_KEY': key}, capture_output=True, text=True)
                    output = dict(line.split('=', 1) for line in Path(env['GITHUB_OUTPUT']).read_text().splitlines())
                    env.update(dict(line.split('=', 1) for line in Path(env['GITHUB_ENV']).read_text().splitlines()))
                    states[step['id']] = {'outcome': 'success' if result.returncode == 0 else 'failure',
                                          **{'outputs.' + k: v for k, v in output.items()}}
                    return result

                for ident in ('toolchain', 'downloads', 'ccache', 'hostpkg'):
                    admit = self.by_id[ident + '-admission']
                    save = self.by_id['save-' + ident]
                    verify = self.by_id['verify-' + ident]
                    key = 'fixture-' + ident
                    if self.gate(admit['if'], states, env):
                        result = run(admit, key)
                        if not (mode == 'measure-failure' and ident == 'toolchain'):
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertGreater(int(states[admit['id']]['outputs.candidate_bytes']), 0)
                    if self.gate(save['if'], states, env):
                        saved.append(ident)
                        states[save['id']] = {'outcome': 'failure' if mode == 'action-failure' and ident == affected else 'success'}
                        if not (ident == affected and mode in ('unconfirmed', 'action-failure')):
                            remote.append(entry(len(remote) + 1, key=key))
                    if self.gate(verify['if'], states, env):
                        run(verify, key)
                tiers = ['toolchain', 'downloads', 'ccache', 'hostpkg']
                expected = tiers[1:] if mode in ('denied', 'measure-failure') else (
                    tiers[:tiers.index(affected) + 1] if affected else tiers)
                self.assertEqual(saved, expected)
                self.assertEqual(env.get('CACHE_SAVES_BLOCKED', 'false'), 'true' if affected else 'false')


if __name__ == '__main__':
    unittest.main()
