#!/usr/bin/env python3
"""Offline policy/contract tests; fixtures are not firmware build evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'Scripts' / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load('Prepare')
verify = load('Verify')


class PolicyTests(unittest.TestCase):
    def test_release_pair(self):
        official = {'stable_version': '26.01.1'}
        donor = dict(tag_name='v26.01.1', draft=False, prerelease=False, html_url='test', published_at='test')
        with patch.object(prepare, 'get_json', side_effect=[official, donor]):
            self.assertEqual(prepare.resolve()['official_tag'], 'v26.01.1')
        donor['tag_name'] = 'v25.12.2'
        with patch.object(prepare, 'get_json', side_effect=[official, donor]):
            with self.assertRaises(ValueError):
                prepare.resolve()

    def test_reject_prerelease(self):
        for tag in ('v25.12.2-rc1', 'main', 'v25.12.2;exit', '../v25.12.2'):
            with self.assertRaises(ValueError):
                prepare.stable_tag(tag)

    def test_unknown_delta_fails_before_writes(self):
        with tempfile.TemporaryDirectory() as d, patch.object(prepare, 'delta', return_value=('unknown', {})), patch.object(prepare, 'run', return_value='a'*40):
            out = Path(d) / 'output'
            with self.assertRaisesRegex(ValueError, 'Unreviewed'):
                prepare.prepare(Path(d), Path(d), out, {})
            self.assertFalse(out.exists())

    def test_edit_gate_tracks_content_not_commits(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d)/'official', Path(d)/'donor'
            a.mkdir(); b.mkdir()
            name = 'hook.mk'
            (a/name).write_text('common\nofficial\n')
            (b/name).write_text('common\nNSS hook\n')
            policy = dict(take=[name], edit_sha256={name: prepare.file_delta(a, b, name)},
                          watch_patterns=[r'patches/nss/.*'])
            changes = {name: [420, 420], 'include/version.mk': [420, 420],
                       'arbitrary/unrelated/new-file': [None, 420]}
            prepare.validate_delta(a, b, policy, changes)
            # Shared upstream evolution and shifted lines are not a commit pin.
            for tree in (a, b):
                (tree/name).write_text('new upstream context\n' + (tree/name).read_text())
            prepare.validate_delta(a, b, policy, changes)
            (b/name).write_text((b/name).read_text() + 'unreviewed command\n')
            with self.assertRaisesRegex(ValueError, 'NSS content'):
                prepare.validate_delta(a, b, policy, changes)
            with self.assertRaisesRegex(ValueError, 'missing'):
                prepare.validate_delta(a, b, policy, {})

    def test_new_nss_patch_and_mode_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d)/'official', Path(d)/'donor'
            a.mkdir(); b.mkdir()
            name = 'hook.mk'
            (b/name).write_text('NSS hook\n')
            policy = dict(take=[name], edit_sha256={name: prepare.file_delta(a, b, name)},
                          watch_patterns=[r'patches/nss/.*'])
            with self.assertRaisesRegex(ValueError, 'NSS extension'):
                prepare.validate_delta(a, b, policy, {name: [], 'patches/nss/new.patch': []})
            (b/name).chmod(0o755)
            with self.assertRaisesRegex(ValueError, 'NSS content'):
                prepare.validate_delta(a, b, policy, {name: []})
            (b/name).unlink()
            (b/name).symlink_to('/etc/hosts')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                prepare.validate_delta(a, b, policy, {name: []})

    def test_no_unreviewed_donor_defaults(self):
        policy = json.loads((ROOT/'Config/nss-policy.json').read_text())
        self.assertNotIn('ignored_prefixes', policy)
        self.assertNotIn('ignored_upstream_paths', policy)
        self.assertEqual(set(policy['take']), set(policy['edit_sha256']))
        for name in ('include/netfilter.mk', 'include/version.mk',
                     'package/kernel/qca-ssdk/patches/0012-suppress-noisy-error-log.patch',
                     'target/linux/qualcommax/Makefile',
                     'target/linux/qualcommax/base-files/etc/init.d/set-irq-affinity',
                     'target/linux/qualcommax/base-files/etc/init.d/smp_affinity',
                     'target/linux/qualcommax/base-files/etc/uci-defaults/15_smp_affinity.sh',
                     'target/linux/qualcommax/base-files/etc/uci-defaults/991_set-network.sh'):
            self.assertNotIn(name, policy['take'])

    def test_in_tree_sources(self):
        self.assertEqual(prepare.nss_packages(), ROOT/'package/qca-nss')

    def test_no_external_feed_in_output(self):
        # Exercise real copy/transplant logic using tiny git trees.
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            official, donor, output = (root/name for name in ('official', 'donor', 'output'))
            for tree in (official, donor):
                (tree/'target/linux/generic').mkdir(parents=True)
                (tree/'target/linux/generic/kernel-6.12').write_text('same kernel')
                (tree/'package/network/services/hostapd/patches').mkdir(parents=True)
                (tree/'Config.in').write_text('config\n')
                (tree/'feeds.conf.default').write_bytes(b'src-git official https://example.invalid/feed\r\n')
                subprocess.run(['git', 'init', '-q', str(tree)], check=True)
                subprocess.run(['git', '-C', str(tree), 'add', '.'], check=True)
                subprocess.run(['git', '-C', str(tree), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            policy = dict(take=[], edit_sha256={}, watch_patterns=[])
            original = json.loads
            def loads(text, *args, **kwargs):
                value = original(text, *args, **kwargs)
                return policy if 'watch_patterns' in value else value
            with patch.object(prepare.json, 'loads', side_effect=loads), contextlib.redirect_stdout(io.StringIO()):
                prepare.prepare(official, donor, output, {})
            self.assertEqual((output/'feeds.conf.default').read_bytes(), (official/'feeds.conf.default').read_bytes())
            self.assertTrue((output/'package/qca-nss/qca-nss-drv/Makefile').is_file())
            lock = json.loads((output/'source-lock.json').read_text())
            self.assertNotIn('VIKING-style', lock['nss_source'])

    def test_exact_four_images(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            images = root / 'bin/targets/qualcommax/ipq807x'
            images.mkdir(parents=True)
            for v in (1, 2):
                for kind in ('factory', 'sysupgrade'):
                    (images / f'immortalwrt-qualcommax-ipq807x-linksys_mx4200v{v}-squashfs-{kind}.bin').write_bytes(b'TEST FIXTURE ONLY')
            verify.images(root)
            self.assertEqual(len(list((root/'upload').iterdir())), 4)

    def test_missing_image_fails(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                verify.images(Path(d))
            self.assertFalse((Path(d)/'upload').exists())

    def test_policy_paths(self):
        data = json.loads((ROOT/'Config/nss-policy.json').read_text())
        self.assertEqual(len(data['take']), len(set(data['take'])))
        self.assertTrue(all(not p.startswith('/') and '..' not in Path(p).parts for p in data['take']))
        self.assertFalse(any('/lib/upgrade/' in p or '/image/' in p for p in data['take']))

    def test_shell_syntax(self):
        for path in (ROOT/'Scripts').glob('*.sh'):
            subprocess.run(['bash', '-n', str(path)], check=True)


if __name__ == '__main__':
    unittest.main()
