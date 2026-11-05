"""Exercise independent Release retention with a private gh boundary."""
from pathlib import Path
import tempfile
import unittest

from test_dual_publish import replay as replay_publish, staged_fixture


def row(tag, rank, **kwargs):
    return dict(tag_name=tag, id=rank, published_at=f'2026-10-{rank:02}T00:00:00Z',
                draft=False, prerelease=False) | kwargs


class ReleaseRetention(unittest.TestCase):
    def replay(self, pages, fault='none'):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            staged_fixture(p)
            mode = {'none':'fresh', 'create':'create-error', 'malformed':'bad-json'}.get(fault,fault)
            result,calls = replay_publish(p,pages,mode)
            return result, [a[2] for a in calls if a[:2] == ['release','delete']]

    def test_readback_failures_protect_old_releases(self):
        pages = [[row('MX4200-ImmortalWrt-current', 10), row('MX4200-ImmortalWrt-previous', 9), row('MX4200-ImmortalWrt-old', 1)]]
        for fault in ('readback', 'malformed', 'missing', 'extra', 'name', 'duplicate',
                      'size', 'state', 'digest', 'tag', 'title', 'tag-sha', 'tag-ref', 'draft', 'prerelease',
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
