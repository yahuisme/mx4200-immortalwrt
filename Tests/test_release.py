"""Run the publisher against an executable gh double; never contact GitHub."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
TAG = 'MX4200_ImmortalWrt_v24.10.2_r33000_26.09.12-12.00.00'

MOCK_GH = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['GH_STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
s['calls'].append(a)
def done(value=None):
    p.write_text(json.dumps(s))
    if value is not None:
        print(json.dumps(value))
    sys.exit(0)
if a[0] == 'api':
    if s.get('fail_api'):
        p.write_text(json.dumps(s))
        sys.exit(1)
    endpoint = a[1]
    if endpoint.endswith('/commits/main'):
        done({'sha': s['head']})
    if '/actions/runs/' in endpoint:
        assert os.environ['GH_TOKEN'] == 'read-token'
        done({'id': 200, 'head_sha': os.environ['GITHUB_SHA'], 'head_branch': 'main',
              'created_at': '2026-09-12T03:00:00Z'})
    if '/git/matching-refs/' in endpoint:
        done(s.get('refs', []))
    if '/releases?' in endpoint:
        assert '--paginate' in a and '--slurp' in a
        done(s['pages'])
if a[:2] == ['release', 'create']:
    assert '--draft' in a and '--latest=false' in a
    s['created'] = a[2]
    if s.get('advance_head'):
        s['head'] = 'b' * 40
    done()
if a[:2] == ['release', 'view']:
    done({'tagName': a[2], 'isDraft': not s.get('published', False),
          'assets': [{'name': n, 'size': 1} for n in s['assets']]})
if a[:2] == ['release', 'edit']:
    s['published'] = True
    done()
if a[:2] == ['release', 'delete']:
    s.setdefault('deleted', []).append(a[2])
    done()
raise SystemExit('Unexpected gh command: ' + repr(a))
'''


class ReleaseTests(unittest.TestCase):
    def run_release(self, **changes):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'gh').write_text(MOCK_GH)
            (tmp / 'gh').chmod(0o755)
            (tmp / 'upload').mkdir()
            names = [f'image-linksys_mx4200v{v}-squashfs-{k}.bin'
                     for v in (1, 2) for k in ('factory', 'sysupgrade')]
            for name in names:
                (tmp / 'upload' / name).write_bytes(b'x')
            (tmp / 'release-notes.md').write_text('Firmware notes\n')
            state = dict(head=SHA, pages=[[]], calls=[], assets=names)
            state.update(changes)
            (tmp / 'state.json').write_text(json.dumps(state))
            result = subprocess.run(
                [sys.executable, str(ROOT / 'Scripts/Release.py'), str(tmp)],
                env={**os.environ, 'PATH': f'{tmp}:' + os.environ['PATH'],
                     'GH_STATE': str(tmp / 'state.json'), 'GITHUB_REPOSITORY': 'owner/repo',
                     'GITHUB_SHA': SHA, 'GITHUB_RUN_ID': '200', 'GITHUB_RUN_NUMBER': '20',
                     'GITHUB_REF': 'refs/heads/main', 'GH_TOKEN': 'publish-token',
                     'GH_READ_TOKEN': 'read-token',
                     'WRT_RELEASE_NAME': TAG}, text=True, capture_output=True)
            return result, json.loads((tmp / 'state.json').read_text())

    def test_publish_then_prune_all_pages_only_safe_product(self):
        old = dict(tag_name=TAG.replace('12.00.00', '11.00.00'), draft=False,
                   prerelease=False, published_at='2026-09-11T03:00:00Z', body='legacy')
        other = {**old, 'tag_name': 'MX4200_other'}
        draft = {**old, 'tag_name': TAG.replace('12.00.00', '10.00.00'), 'draft': True}
        second = {**old, 'tag_name': TAG.replace('12.00.00', '09.00.00')}
        result, state = self.run_release(pages=[[other, draft, old], [second]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(state.get('published'))
        self.assertEqual(state.get('deleted'), [old['tag_name'], second['tag_name']])
        create = next(c for c in state['calls'] if c[:2] == ['release', 'create'])
        self.assertEqual(sum(x.endswith('.bin') for x in create), 4)
        self.assertEqual(create[create.index('--target') + 1], SHA)

    def test_newer_or_same_run_blocks_reverse_completion(self):
        for number in (20, 21):
            with self.subTest(number=number):
                newer = dict(tag_name=TAG.replace('12.00.00', '13.00.00'), draft=False,
                             prerelease=False, published_at='2026-09-12T04:00:00Z',
                             body=f'MX4200 build run: `{number}`')
                result, state = self.run_release(pages=[[], [newer]])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('created', state)
                self.assertNotIn('deleted', state)

    def test_legacy_release_published_after_run_blocks_rerun(self):
        newer = dict(tag_name=TAG.replace('12.00.00', '13.00.00'), draft=False,
                     prerelease=False, published_at='2026-09-12T03:00:00Z', body='')
        result, state = self.run_release(pages=[[newer]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('created', state)

    def test_same_second_release_or_orphan_tag_never_overwritten(self):
        for changes, code in (({'pages': [[{'tag_name': TAG}]]}, 0),
                              ({'refs': [{'ref': f'refs/tags/{TAG}'}]}, 1)):
            with self.subTest(changes=changes):
                result, state = self.run_release(**changes)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertNotIn('created', state)
                self.assertNotIn('deleted', state)

    def test_main_advance_during_upload_leaves_draft_without_pruning(self):
        result, state = self.run_release(advance_head=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('created', state)
        self.assertNotIn('published', state)
        self.assertNotIn('deleted', state)

    def test_asset_verification_failure_never_publishes_or_prunes(self):
        result, state = self.run_release(assets=['wrong.bin'])
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('published', state)
        self.assertNotIn('deleted', state)

    def test_api_failure_never_writes(self):
        result, state = self.run_release(fail_api=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('created', state)
        self.assertNotIn('deleted', state)

    def test_workflow_uses_shared_noncancelling_lock(self):
        text = (ROOT / '.github/workflows/MX4200.yml').read_text()
        self.assertIn('concurrency:\n  group: mx4200-immortalwrt-release\n  cancel-in-progress: false', text)
        self.assertIn('python3 Scripts/Release.py /mnt/build_wrt', text)
        self.assertNotIn('gh release list', text)

    def test_old_sha_rerun_never_writes(self):
        result, state = self.run_release(head='b' * 40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c[:2] in (['release', 'create'], ['release', 'delete'],
                                     ['release', 'edit']) for c in state['calls']))


if __name__ == '__main__':
    unittest.main()
