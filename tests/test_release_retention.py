"""Exercise Release retention with a private gh boundary."""
from pathlib import Path
import tempfile
import unittest

from test_dual_publish import GROUPS, TAG_SUFFIX, full_page, replay as replay_publish, staged_fixture

CURRENT = [device + TAG_SUFFIX for device in GROUPS.values()]
PREVIOUS = 'MX4200-ImmortalWrt-r122-26.11.23_00.00.00'
OLD = 'MX4200-ImmortalWrt-25.12.2-r100-26.11.01_00.00.00'


def row(tag, rank, **kwargs):
    return dict(tag_name=tag, id=rank, published_at=f'2026-10-{rank:02}T00:00:00Z',
                draft=False, prerelease=False) | kwargs


class ReleaseRetention(unittest.TestCase):
    def replay(self, pages, fault='none'):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            staged_fixture(base)
            mode = {'none': 'fresh', 'create': 'create-error', 'malformed': 'bad-json'}.get(fault, fault)
            result, calls = replay_publish(base, pages, mode)
            return result, [a[2] for a in calls if a[:2] == ['release', 'delete']]

    def test_only_older_production_tags_are_pruned(self):
        current = [row(tag, rank) for rank, tag in enumerate(CURRENT, 10)]
        older = [row('MX4200-ImmortalWrt-25.12.2-r100-26.10.08_00.00.00', 8),
                 row('MX4300-HomeWRK-ImmortalWrt-r100-26.10.09_00.00.00', 9)]
        protected = [row('MX4200-ImmortalWrt-r120-26.10.07_00.00.00', 12),
                     row('MX4300-ImmortalWrt-r119-26.10.07_00.00.00', 13),
                     row('MX4200-ImmortalWrt-manual-recovery', 7),
                     row('MX4200-ImmortalWrt-r99-26.10.07_00.00.00', 14,
                         published_at=current[0]['published_at']),
                     row('MX4300-ImmortalWrt-r130-26.11.25_00.00.00', 6),
                     row('MX4200-ImmortalWrt-r90-26.10.00_00.00.00', 5)]
        result, deleted = self.replay([full_page([current[0], older[0], *protected]),
                                       [current[1], older[1]]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(deleted, [r['tag_name'] for r in older])

    def test_uncertain_dual_inventory_never_prunes_either_group(self):
        current = [row(tag, rank) for rank, tag in enumerate(CURRENT, 10)]
        old = row(OLD, 8)
        first = full_page([*current, old])
        invalid_date = row('MX4300-ImmortalWrt-r121-26.10.09_00.00.00', 9,
                           published_at='2026-10-32T00:00:00Z')
        for pages, diagnostic in (([[current[0], old]], 'Current publication missing'),
                                  ([first, [old]], 'Duplicate Release ID or tag'),
                                  ([first, [dict(old, id=90)]], 'Duplicate Release ID or tag'),
                                  ([first, [dict(old, tag_name='Other')]], 'Duplicate Release ID or tag'),
                                  ([first, [invalid_date]], 'day is out of range')):
            with self.subTest(diagnostic=diagnostic):
                result, deleted = self.replay(pages)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(deleted, [])
                self.assertIn(diagnostic, result.stderr)
                self.assertIn('retaining both groups', result.stdout)

    def test_readback_failures_protect_old_releases(self):
        pages = [[row(CURRENT[0], 10), row(CURRENT[1], 11), row(PREVIOUS, 9), row(OLD, 1)]]
        for fault in ('readback', 'malformed', 'missing', 'extra', 'name', 'duplicate',
                      'size', 'state', 'digest', 'tag', 'title', 'tag-sha', 'tag-ref', 'draft', 'prerelease',
                      'download-corrupt', 'download-failed'):
            with self.subTest(fault=fault):
                result, deleted = self.replay(pages, fault)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(deleted, [])
        result, deleted = self.replay(pages, 'no-digest')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(deleted, [PREVIOUS, OLD])

    def test_zero_one_two_three(self):
        for count in range(4):
            rows = [row(CURRENT[1], 11)]
            if count:
                rows.append(row(CURRENT[0], 10))
            older = [row(f'MX4200-ImmortalWrt-r10{i}-26.11.0{i}_00.00.00', i) for i in range(1, count)]
            rows.extend(older)
            result, deleted = self.replay([rows])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(deleted, [r['tag_name'] for r in older])

    def test_pagination_publication_order_and_protected_releases(self):
        first = full_page([row(OLD, 1), row('Other_keep', 20),
                           row('MX4200-ImmortalWrt-r81-26.11.10_00.00.00', 21, draft=True)])
        pages = [first, [row(PREVIOUS, 9), row(CURRENT[0], 10), row(CURRENT[1], 11),
                         row('MX4200_ImmortalWrt_26.11.11-00.00.00_r82', 22, prerelease=True)]]
        result, deleted = self.replay(pages)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(deleted, [OLD, PREVIOUS])

    def test_failures_never_delete_from_partial_inventory(self):
        pages = [[row(CURRENT[0], 10), row(CURRENT[1], 11), row(PREVIOUS, 9), row(OLD, 1)]]
        for fault in ('create', 'list'):
            result, deleted = self.replay(pages, fault)
            self.assertEqual(deleted, [])
            self.assertEqual(result.returncode != 0, fault == 'create')
        for data in ([], [[row(OLD, 1)]], {'malformed': True}):
            result, deleted = self.replay(data)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(deleted, [])
            self.assertIn('retaining both groups', result.stdout)

    def test_inconsistent_page_sizes_disable_cleanup(self):
        current = [row(tag, rank) for rank, tag in enumerate(CURRENT, 10)]
        first = [*current, row(OLD, 8)]
        full = full_page(first)
        for case, pages in (
                ('empty trailing page', [full, []]),
                ('short nonfinal page', [first, [row('Other-final', 50)]]),
                ('overlong page', [[*full, row('Other-extra', 51)]])):
            with self.subTest(case=case):
                result, deleted = self.replay(pages)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(deleted, [])
                self.assertIn('Inconsistent Release inventory page sizes', result.stderr)
                self.assertIn('retaining both groups', result.stdout)

    def test_missing_publication_timestamp_disables_cleanup(self):
        for tag in (*CURRENT, OLD):
            with self.subTest(tag=tag):
                rows = [row(CURRENT[0], 10), row(CURRENT[1], 11), row(OLD, 1)]
                next(r for r in rows if r['tag_name'] == tag).pop('published_at')
                result, deleted = self.replay([rows])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(deleted, [])
                self.assertIn('retaining both groups', result.stdout)

    def test_delete_failure_is_visible(self):
        result, deleted = self.replay([[row(CURRENT[0], 10), row(CURRENT[1], 11), row(PREVIOUS, 9),
                                       row(OLD, 1)]], 'delete')
        self.assertEqual(deleted, [PREVIOUS, OLD])
        self.assertEqual(result.returncode, 0)
        self.assertIn('::warning::Failed to delete release', result.stdout)
