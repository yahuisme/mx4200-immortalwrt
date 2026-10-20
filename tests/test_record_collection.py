"""Actual metadata helper and publish shell; Git/gh remain entirely local."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_cache_workflow import ROOT, step
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
    (base/'.custom-revisions.tsv').write_text(''.join(f'{name}\thttps://example.invalid/{name}\t'+'a'*40+'\n' for name in ('yahuisme/packages','luci-theme-aurora','luci-app-aurora-config')))



class BuildRecordTests(unittest.TestCase):
    def test_actual_helper_success_and_missing_metadata(self):
        for missing in ('', '.config', '.custom-revisions.tsv', 'manifest', 'feed'):
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
                    self.assertEqual({r['name'] for r in revisions}, {'source', 'feed/packages', 'custom/yahuisme/packages', 'custom/luci-theme-aurora', 'custom/luci-app-aurora-config'})
                    sha = subprocess.check_output(['git', '-C', tmp, 'rev-parse', 'HEAD'], text=True).strip()
                    self.assertEqual(revisions[0]['sha'], sha)

    def test_malformed_custom_records_keep_partial_evidence(self):
        for fault in ('empty', 'missing-row', 'duplicate', 'bad-sha', 'blank-row'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                safety.ReleaseTests().fixture(base)
                prepare(base)
                custom = base / '.custom-revisions.tsv'
                lines = custom.read_text().splitlines()
                if fault == 'empty': custom.write_text('')
                if fault == 'missing-row': custom.write_text('\n'.join(lines[:-1]) + '\n')
                if fault == 'duplicate': custom.write_text('\n'.join([lines[0], lines[0], lines[2]]) + '\n')
                if fault == 'bad-sha': custom.write_text(custom.read_text().replace('a' * 40, 'not-a-sha', 1))
                if fault == 'blank-row': custom.write_text(custom.read_text() + '\n')
                # Source/feed identities are read from Git, not a duplicate text log.
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'), tmp,
                                         str(base / 'record')], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(json.loads((base / 'record/diagnostics.json').read_text())['errors'])
                self.assertTrue((base / 'record/sha256sums').read_text())
                self.assertEqual((base / 'record/final.config').read_bytes(), (base / '.config').read_bytes())

    def test_copy_errors_retain_later_evidence(self):
        for collision in ('final.config', 'targets'):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                output, _ = safety.ReleaseTests().fixture(base)
                prepare(base)
                record = base / 'record'
                record.mkdir()
                if collision == 'final.config':
                    (record / collision).mkdir()
                else:
                    (record / collision).write_text('not a directory')
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'),
                                         tmp, str(record)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                errors = json.loads((record / 'diagnostics.json').read_text())['errors']
                self.assertTrue(any('Copy failed:' in error for error in errors))
                self.assertEqual((record / 'custom-revisions.tsv').read_bytes(),
                                 (base / '.custom-revisions.tsv').read_bytes())
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
                         "${{ !cancelled() && github.ref == 'refs/heads/main' && steps.stage.outcome == 'success' }}")
