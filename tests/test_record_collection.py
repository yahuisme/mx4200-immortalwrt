"""Actual metadata helper and publish shell; Git/gh remain entirely local."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_cache_workflow import ROOT, step
from test_record_contract import external_provenance_fixture, write_external_fixture
class safety:
    class ReleaseTests:
        def fixture(self, base):
            output = base / 'bin/targets/qualcommax/ipq807x'
            output.mkdir(parents=True)
            (base / '.config').write_text('CONFIG_FIXTURE=y\n')
            for device in ('mx4200v1', 'mx4200v2'):
                for kind in ('factory', 'sysupgrade'):
                    (output / f'immortalwrt-qualcommax-ipq807x-linksys_{device}-squashfs-{kind}.bin').write_bytes(b'fixture-not-firmware')
            return output, {}
IMAGE = 'immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-factory.bin'
def prepare(base):
    for path in [base, base/'feeds/packages']:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', str(path)], check=True)
        subprocess.run(['git', '-C', str(path), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture'], check=True)
        subprocess.run(['git', '-C', str(path), 'remote', 'add', 'origin', 'https://example.invalid/local'], check=True)
    profiles = base/'bin/targets/qualcommax/ipq807x/profiles.json'
    if not profiles.exists():
        profiles.write_text('{}\n')
    (base/'bin/targets/qualcommax/ipq807x/fixture.manifest').write_text('fixture - 1\n')
    write_external_fixture(base)



class BuildRecordTests(unittest.TestCase):
    def test_actual_helper_success_and_missing_metadata(self):
        for missing in ('', '.config', '.external-packages/provenance.json', 'manifest', 'feed'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                output, _ = safety.ReleaseTests().fixture(base)
                prepare(base)
                if missing == 'manifest':
                    (output / 'fixture.manifest').unlink()
                elif missing == 'feed':
                    (base / 'feeds/packages/.git').rename(base / 'feed-git-hidden')
                elif missing:
                    (base / missing).unlink()
                (output / IMAGE).chmod(0o600)
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'), tmp,
                                         str(base / 'record')], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not missing, result.stderr)
                record = base / 'record'
                self.assertEqual(bool(json.loads((record / 'diagnostics.json').read_text())['errors']), bool(missing))
                self.assertIn(hashlib.sha256((output / IMAGE).read_bytes()).hexdigest(),
                              (record / 'sha256sums').read_text())
                self.assertFalse(list(record.glob('**/*.bin')))
                for path in record.rglob('*'):
                    if path.is_file():
                        self.assertEqual(path.stat().st_mode & 0o444, 0o444)
                if not missing:
                    revisions = json.loads((record / 'revisions.json').read_text())
                    self.assertEqual({r['name'] for r in revisions}, {'source', 'feed/packages'})
                    self.assertEqual(json.loads((record / 'external-packages.json').read_text()),
                                     external_provenance_fixture())
                    self.assertEqual(json.loads((record / 'build.json').read_text())['custom_sources'], [])
                    self.assertFalse((record / 'custom-revisions.tsv').exists())
                    sha = subprocess.check_output(['git', '-C', tmp, 'rev-parse', 'HEAD'], text=True).strip()
                    self.assertEqual(revisions[0]['sha'], sha)
                else:
                    self.assertIsNotNone(json.loads((record / 'build.json').read_text())['source'])
                if missing == '.external-packages/provenance.json':
                    self.assertIsNone(json.loads((record / 'build.json').read_text())['external_packages'])

    def test_malformed_external_records_keep_partial_evidence(self):
        faults = {
            'null': lambda data: None,
            'list': lambda data: [],
            'version': lambda data: dict(data, version=2),
            'boolean-version': lambda data: dict(data, version=True),
            'architecture': lambda data: dict(data, architecture='x86_64'),
            'missing-repositories': lambda data: {k: v for k, v in data.items() if k != 'repositories'},
            'repositories-not-list': lambda data: dict(data, repositories={}),
            'missing-repository': lambda data: dict(data, repositories=data['repositories'][:-1]),
            'duplicate-repository': lambda data: dict(data, repositories=[data['repositories'][0]] * 2),
            'extra-repository': lambda data: dict(data, repositories=data['repositories'] + [dict(data['repositories'][0], name='other')]),
            'retired-repository': lambda data: dict(data, repositories=[dict(data['repositories'][0], name='daeuniverse'), data['repositories'][1]]),
            'null-repository': lambda data: dict(data, repositories=[None, data['repositories'][1]]),
            'packages-not-list': lambda data: dict(data, packages={}),
            'missing-package': lambda data: dict(data, packages=data['packages'][:-1]),
            'duplicate-package': lambda data: dict(data, packages=[data['packages'][0]] + data['packages'][:-1]),
            'extra-package': lambda data: dict(data, packages=data['packages'] + [dict(data['packages'][0], name='other')]),
            'retired-package': lambda data: dict(data, packages=[dict(data['packages'][0], name='honk', filename='honk-1.0-fixture-r1.apk')] + data['packages'][1:]),
            'alpha-provider': lambda data: dict(data, packages=[dict(data['packages'][0], name='mihomo-alpha', filename='mihomo-alpha-1.0-fixture-r1.apk')] + data['packages'][1:]),
            'null-package': lambda data: dict(data, packages=[None] + data['packages'][1:]),
        }
        for field, value in (
                ('url', ''), ('url', 'http://example.invalid/repository'),
                ('url', 'https:///repository'), ('url', 'https://user:password@example.invalid/repo'),
                ('index_sha256', 'a' * 63), ('index_sha256', 'g' * 64),
                ('key_sha256', None), ('key_sha256', 'b' * 65)):
            faults[f'repository-{field}-{value}'] = lambda data, field=field, value=value: dict(
                data, repositories=[dict(data['repositories'][0], **{field: value}), data['repositories'][1]])
        for field, value in (
                ('version', ''), ('version', '  '), ('version', 1),
                ('arch', 'x86_64'), ('repository', 'other'), ('repository', 'eamonxg'),
                ('sha256', 'short'), ('sha256', 'g' * 64), ('sha256', None),
                ('filename', ''), ('filename', '../mihomo-meta.apk'), ('filename', 'different.apk')):
            faults[f'package-{field}-{value}'] = lambda data, field=field, value=value: dict(
                data, packages=[dict(data['packages'][0], **{field: value})] + data['packages'][1:])
        for fault in ('empty', 'invalid-json', *faults):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                safety.ReleaseTests().fixture(base)
                prepare(base)
                provenance = base / '.external-packages/provenance.json'
                if fault == 'empty': provenance.write_text('')
                elif fault == 'invalid-json': provenance.write_text('{')
                else: provenance.write_text(json.dumps(faults[fault](external_provenance_fixture())))
                # Source/feed identities are read from Git, not a duplicate text log.
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'), tmp,
                                         str(base / 'record')], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(any('External package provenance invalid:' in error for error in
                                    json.loads((base / 'record/diagnostics.json').read_text())['errors']))
                self.assertTrue((base / 'record/sha256sums').read_text())
                self.assertEqual((base / 'record/final.config').read_bytes(), (base / '.config').read_bytes())
                record = json.loads((base / 'record/build.json').read_text())
                self.assertIsNone(record['external_packages'])
                self.assertEqual(record['custom_sources'], [])
                self.assertEqual({r['name'] for r in json.loads((base / 'record/revisions.json').read_text())},
                                 {'source', 'feed/packages'})
                if fault != 'empty':
                    self.assertEqual((base / 'record/external-packages.json').read_bytes(), provenance.read_bytes())

    def test_copy_errors_retain_later_evidence(self):
        for collision in ('final.config', 'targets', 'external-packages.json'):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                output, _ = safety.ReleaseTests().fixture(base)
                prepare(base)
                record = base / 'record'
                record.mkdir()
                if collision in ('final.config', 'external-packages.json'):
                    (record / collision).mkdir()
                else:
                    (record / collision).write_text('not a directory')
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'),
                                         tmp, str(record)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                errors = json.loads((record / 'diagnostics.json').read_text())['errors']
                self.assertTrue(any('Copy failed:' in error for error in errors))
                if collision != 'external-packages.json':
                    self.assertEqual((record / 'external-packages.json').read_bytes(),
                                     (base / '.external-packages/provenance.json').read_bytes())
                self.assertEqual(json.loads((record / 'build.json').read_text())['external_packages'],
                                 external_provenance_fixture())
                self.assertIn(hashlib.sha256((output / IMAGE).read_bytes()).hexdigest(),
                              (record / 'sha256sums').read_text())

    def test_dpkg_inventory_success_empty_and_failure(self):
        for mode in ('ok', 'empty', 'failure'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                safety.ReleaseTests().fixture(base)
                prepare(base)
                commands = base / 'commands'
                commands.mkdir()
                stub = commands / 'dpkg-query'
                stub.write_text('#!/bin/sh\n' + {
                    'ok': "printf 'z\\tarm64\\t2\\na\\tall\\t1\\n'\n",
                    'empty': 'exit 0\n', 'failure': 'exit 17\n'}[mode])
                stub.chmod(0o755)
                record = base / 'record'
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'),
                    tmp, str(record)], capture_output=True, text=True,
                    env=dict(os.environ, PATH=str(commands)+':'+os.environ['PATH']))
                self.assertEqual(result.returncode == 0, mode == 'ok', result.stderr)
                self.assertEqual(bool(json.loads((record / 'diagnostics.json').read_text())['errors']), mode != 'ok')
                self.assertTrue((record / 'sha256sums').read_text())
                if mode == 'ok':
                    self.assertEqual((record / 'dpkg-packages.tsv').read_text(), 'a\tall\t1\nz\tarm64\t2\n')

    def test_feed_failures_keep_stderr(self):
        lines = [line.strip() for line in step('Prepare source and cache key')['run'].splitlines()
                 if './scripts/feeds ' in line]
        self.assertEqual(len(lines), 2)
        for line in lines:
            with self.subTest(line=line), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / 'scripts').mkdir()
                feeds = base / 'scripts/feeds'
                feeds.write_text('#!/bin/sh\nprintf "feed diagnostic" >&2\nexit 17\n')
                feeds.chmod(0o755)
                result = subprocess.run(['bash', '-e', '-c', line], cwd=base,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('feed diagnostic', result.stderr)

    def test_artifact_contract(self):
        collect, upload = step('Collect build record'), step('Upload build record')
        self.assertTrue(collect['continue-on-error'])
        self.assertTrue(upload['continue-on-error'])
        self.assertEqual(collect['if'], '${{ always() }}')
        self.assertEqual(upload['if'], '${{ always() }}')
        self.assertEqual(upload['with']['retention-days'], 30)
        self.assertEqual(upload['with']['path'], 'build-record/')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        self.assertEqual(step('Publish firmware and prune releases')['if'],
                         "${{ !cancelled() && github.ref == 'refs/heads/main' && steps.stage.outcome == 'success' && steps.record.outcome == 'success' && steps.record_upload.outcome == 'success' }}")
