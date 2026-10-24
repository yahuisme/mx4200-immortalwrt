"""Exercise the real publication shell with a private gh boundary."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
STEPS = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']
CODE = next(s['run'] for s in STEPS if s['name'] == 'Publish firmware and prune releases')
STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f:
    f.write(json.dumps(a) + '\\n')
if a[:2] == ['release', 'create']:
    sys.exit(1 if os.environ['FAULT'] == 'create' else 0)
elif a[0] == 'api':
    if a[1] == 'repos/fixture/repo/git/ref/heads/main':
        print(os.environ['GITHUB_SHA']); sys.exit(0)
    if '/releases/assets/' in a[1]:
        assert a[2:] == ['-H', 'Accept: application/octet-stream']
        fault = os.environ['FAULT']
        sys.stdout.buffer.write(b'wrong content' if fault == 'download-corrupt' else b'fixture image')
        sys.exit(8 if fault == 'download-failed' else 0)
    if '/releases/tags/' in a[-1]:
        import hashlib
        assets = [dict(id=i, name=p.name, size=p.stat().st_size, state='uploaded',
                       digest='sha256:' + hashlib.sha256(p.read_bytes()).hexdigest())
                  for i, p in enumerate(Path(os.environ['IMAGES']).glob('*.bin'), 1)]
        fault = os.environ['FAULT']
        if fault == 'readback': sys.exit(8)
        if fault == 'malformed': print('{'); sys.exit(0)
        if fault == 'missing': assets.pop()
        if fault == 'extra': assets.append(dict(name='metadata.json'))
        if fault == 'name': assets[0]['name'] = 'unexpected.bin'
        if fault == 'duplicate': assets[0] = assets[1]
        if fault == 'size': assets[0]['size'] += 1
        if fault == 'state': assets[0]['state'] = 'new'
        if fault == 'digest': assets[0]['digest'] = 'sha256:wrong'
        if fault in ('no-digest', 'download-corrupt', 'download-failed'):
            for asset in assets: asset.pop('digest')
        print(json.dumps(dict(tag_name='wrong' if fault == 'tag' else os.environ['WRT_RELEASE_NAME'],
                              draft=fault == 'draft', prerelease=fault == 'prerelease', assets=assets)))
        sys.exit(0)
    assert '--paginate' in a and '--slurp' in a
    print(Path(os.environ['ROWS']).read_text())
    sys.exit(1 if os.environ['FAULT'] == 'list' else 0)
elif a[:2] == ['release', 'delete']:
    assert len(a) == 5 and a[3:] == ['--cleanup-tag', '-y']
    sys.exit(1 if os.environ['FAULT'] == 'delete' else 0)
else:
    raise SystemExit('unexpected gh invocation')
'''


def row(tag, rank, **kwargs):
    return dict(tag_name=tag, id=rank, published_at=f'2026-10-{rank:02}T00:00:00Z',
                draft=False, prerelease=False) | kwargs


class ReleaseRetention(unittest.TestCase):
    def replay(self, pages, fault='none'):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'gh').write_text(STUB)
            (p / 'gh').chmod(0o755)
            (p / 'rows').write_text(json.dumps(pages))
            for device in ('mx4200v1', 'mx4200v2'):
                for kind in ('factory', 'sysupgrade'):
                    (p / f'immortalwrt-qualcommax-ipq807x-linksys_{device}-squashfs-{kind}.bin').write_bytes(b'fixture image')
            env = dict(os.environ, PATH=d + ':' + os.environ['PATH'], IMAGES=d,
                       CALLS=str(p / 'calls'), ROWS=str(p / 'rows'), FAULT=fault,
                       WRT_RELEASE_NAME='MX4200-ImmortalWrt-current', WRT_RELEASE_TITLE='fixture',
                       GITHUB_SHA='a' * 40, GITHUB_REPOSITORY='fixture/repo', RELEASE_NOTES='fixture')
            (p / 'firmware').mkdir()
            for image in p.glob('*.bin'): image.rename(p / 'firmware' / image.name)
            env['IMAGES'] = str(p / 'firmware')
            (p / 'firmware/version.txt').write_text('MX4200-ImmortalWrt-current')
            (p / 'firmware/title.txt').write_text('fixture')
            (p / 'firmware/release-notes.md').write_text('fixture')
            (p / 'scripts').symlink_to(ROOT / 'scripts')
            code = CODE
            result = subprocess.run(['bash', '-eo', 'pipefail', '-c', code], cwd=p,
                                    env=env, capture_output=True, text=True)
            calls = [json.loads(x) for x in (p / 'calls').read_text().splitlines()]
            return result, [a[2] for a in calls if a[:2] == ['release', 'delete']]

    def test_readback_failures_protect_old_releases(self):
        pages = [[row('MX4200-ImmortalWrt-current', 10), row('MX4200-ImmortalWrt-previous', 9), row('MX4200-ImmortalWrt-old', 1)]]
        for fault in ('readback', 'malformed', 'missing', 'extra', 'name', 'duplicate',
                      'size', 'state', 'digest', 'tag', 'draft', 'prerelease',
                      'download-corrupt', 'download-failed'):
            with self.subTest(fault=fault):
                result, deleted = self.replay(pages, fault)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(deleted, [])
        result, deleted = self.replay(pages, 'no-digest')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(deleted, ['MX4200-ImmortalWrt-previous', 'MX4200-ImmortalWrt-old'])

    def test_zero_one_two_three(self):
        for count in range(4):
            rows = [row('MX4200-ImmortalWrt-current', 10)] if count else []
            rows += [row(f'MX4200-ImmortalWrt-old{i}', i) for i in range(1, count)]
            result, deleted = self.replay([rows])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(deleted,
                             (['MX4200-ImmortalWrt-old1'] if count == 2 else
                              ['MX4200-ImmortalWrt-old1', 'MX4200-ImmortalWrt-old2']
                              if count == 3 else []))

    def test_pagination_publication_order_and_protected_releases(self):
        pages = [[row('MX4200-ImmortalWrt-old', 1), row('Other_keep', 20),
                  row('MX4200-ImmortalWrt-draft', 21, draft=True)],
                 [row('MX4200-ImmortalWrt-previous', 9), row('MX4200-ImmortalWrt-current', 10),
                  row('MX4200_ImmortalWrt_preview', 22, prerelease=True)]]
        result, deleted = self.replay(pages)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(deleted, ['MX4200-ImmortalWrt-old', 'MX4200-ImmortalWrt-previous'])

    def test_failures_never_delete_from_partial_inventory(self):
        pages = [[row('MX4200-ImmortalWrt-current', 10), row('MX4200-ImmortalWrt-previous', 9), row('MX4200-ImmortalWrt-old', 1)]]
        for fault in ('create', 'list'):
            result, deleted = self.replay(pages, fault)
            self.assertEqual(deleted, [])
            self.assertEqual(result.returncode != 0, fault == 'create')
        for data in ([], [[row('MX4200-ImmortalWrt-old', 1)]], {'malformed': True}):
            result, deleted = self.replay(data)
            self.assertEqual(deleted, [])
            self.assertIn('::warning::', result.stdout)

    def test_single_release_retention_does_not_require_ordering_metadata(self):
        pages = [[dict(tag_name=tag, draft=False, prerelease=False) for tag in (
            'MX4200-ImmortalWrt-old', 'MX4200_ImmortalWrt_legacy',
            'MX4200-ImmortalWrt-current', 'MX4200-ImmortalWrt-previous')]]
        result, deleted = self.replay(pages)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(deleted, ['MX4200-ImmortalWrt-old', 'MX4200_ImmortalWrt_legacy',
                                   'MX4200-ImmortalWrt-previous'])

    def test_delete_failure_is_visible(self):
        result, deleted = self.replay([[row('MX4200-ImmortalWrt-current', 10), row('MX4200-ImmortalWrt-previous', 9),
                                       row('MX4200-ImmortalWrt-old', 1)]], 'delete')
        self.assertEqual(deleted, ['MX4200-ImmortalWrt-previous', 'MX4200-ImmortalWrt-old'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('::warning::Failed to delete release', result.stdout)
