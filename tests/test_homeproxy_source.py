"""HomeProxy source transition and fail-closed local Git imports."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES_URL = 'https://github.com/yahuisme/packages.git'


class HomeProxySourceTests(unittest.TestCase):
    def test_homeproxy_requested_and_only_theme_externally_sourced(self):
        from scripts.check_defaults import FORBIDDEN_PACKAGES
        from scripts.external_packages import REPOSITORIES
        config = (ROOT / 'user/default/config.diff').read_text()
        for name in ('luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box'):
            self.assertIn(f'CONFIG_PACKAGE_{name}=y', config)
            self.assertNotIn(name, FORBIDDEN_PACKAGES)
        self.assertEqual(set(REPOSITORIES), {'eamonxg'})
        self.assertEqual({p.name for p in (ROOT / 'user/default/files/usr/share/luci/menu.d').glob('*.json')},
                         {'luci-app-ttyd.json', 'luci-app-cpufreq.json'})

    def test_direct_import_preflights_before_clone_or_any_tree_write(self):
        from test_custom_scope import tree_contents
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            donor = base / 'donor'
            subprocess.run(['git', 'init', '-q', '-b', 'main', str(donor)], check=True)
            for name in ('luci-app-homeproxy', 'sing-box'):
                path = donor / name / 'Makefile'
                path.parent.mkdir()
                path.write_text('# direct-import fixture: ' + name + '\n')
            subprocess.run(['git', '-C', str(donor), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(donor), '-c', 'user.name=Fixture', '-c',
                            'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            config = base / 'gitconfig'
            subprocess.run(['git', 'config', '--file', str(config),
                            f'url.{donor.as_uri()}.insteadOf', PACKAGES_URL], check=True)
            script = base / 'packages.sh'
            script.write_text((ROOT / 'scripts/packages.sh').read_text().replace(
                '/cache-scripts/external_packages.py', str(ROOT / 'scripts/external_packages.py')))
            # Positive first: actual source import and native preparation are reachable.
            for source, fault in (('stable-apk-source', ''), ('snapshot-source', ''),
                                  ('snapshot-source', 'version'), ('snapshot-source', 'version-override'),
                                  ('snapshot-source', 'assembly'), ('snapshot-source', 'opkg'),
                                  ('snapshot-source', 'wrong-arch')):
                with self.subTest(source=source, fault=fault):
                    build = base / (source + '-' + (fault or 'valid'))
                    shutil.copytree(ROOT / 'tests/fixtures' / source, build)
                    for name in ('feeds/luci', 'feeds/packages', 'tmp/info/empty'):
                        (build / name).mkdir(parents=True, exist_ok=True)
                    (build / '.custom-revisions.tsv').write_text('previous source provenance\n')
                    for name in ('luci-app-homeproxy', 'sing-box'):
                        path = build / 'package' / name / 'Makefile'
                        path.parent.mkdir()
                        path.write_text('previous recipe\n')
                        (build / 'feeds/luci' / name).symlink_to(path.parent)
                    if fault == 'version':
                        (build / 'include/version.mk').write_text('VERSION_NUMBER:=SNAPSHOTgarbage\n')
                    elif fault == 'version-override':
                        (build / '.config').write_text('CONFIG_VERSION_NUMBER="99.99.0"\n')
                    elif fault == 'opkg':
                        (build / '.config').write_text('# CONFIG_USE_APK is not set\n')
                    elif fault == 'wrong-arch':
                        (build / '.config').write_text('CONFIG_TARGET_ARCH_PACKAGES="aarch64_generic"\n')
                    elif fault == 'assembly':
                        path = build / 'include/image.mk'
                        path.write_text(path.read_text().replace('$(call apk,$(mkfs_cur_target_dir)) --no-scripts',
                                                                 '$(call changed_apk,$(mkfs_cur_target_dir)) --no-scripts'))
                    before = tree_contents(base)
                    result = subprocess.run(['bash', str(script)], cwd=build / 'package',
                        env=dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1', TMPDIR=tmp),
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, not fault, result.stdout + result.stderr)
                    if fault:
                        expected = {'assembly': 'Unsupported upstream assembly boundary',
                                    'version': 'reviewed ImmortalWrt Snapshot',
                                    'version-override': 'without version override',
                                    'opkg': 'require APK and aarch64_cortex-a53',
                                    'wrong-arch': 'require APK and aarch64_cortex-a53'}
                        self.assertIn(expected[fault], result.stderr)
                        self.assertEqual(before, tree_contents(base), 'rejected direct caller changed its input tree')
                        self.assertNotIn('Cloning into', result.stderr)
                    else:
                        for name in ('luci-app-homeproxy', 'sing-box'):
                            self.assertEqual((build / 'package' / name / 'Makefile').read_bytes(),
                                             (donor / name / 'Makefile').read_bytes())
                        self.assertIn('MX_EXTERNAL_PACKAGES:=', (build / '.external-packages.mk').read_text())
                    self.assertFalse(list(base.glob('mx4200-packages.*')))

    def test_local_clone_replaces_feed_recipes_and_records_exact_source(self):
        original = (ROOT / 'scripts/packages.sh').read_text()
        for fault in ('', 'missing-sing-box', 'clone', 'prepare'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = root / 'upstream'
                subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True)
                for name in ('luci-app-homeproxy', 'sing-box'):
                    if fault == 'missing-sing-box' and name == 'sing-box':
                        continue
                    path = repo / name / 'Makefile'
                    path.parent.mkdir(parents=True)
                    path.write_text('# fixture ' + name + '\n')
                subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
                subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c',
                                'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
                sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
                config = root / 'gitconfig'
                config.touch()
                env = dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1', TMPDIR=tmp)
                source = root / 'missing' if fault == 'clone' else repo
                subprocess.run(['git', 'config', '--file', str(config),
                                f'url.{source.as_uri()}.insteadOf', PACKAGES_URL], check=True)
                build = root / 'build'
                for path in ('package', 'feeds/luci', 'feeds/packages'):
                    (build / path).mkdir(parents=True)
                for name in ('luci-app-homeproxy', 'sing-box'):
                    (build / 'feeds/luci' / name).symlink_to(root / 'gone')
                    old = build / 'package' / name / 'Makefile'
                    old.parent.mkdir()
                    old.write_text('old recipe')
                (build / '.custom-revisions.tsv').write_text('stale provenance\n')
                hook = root / 'external.py'
                hook.write_text('import sys\nfrom pathlib import Path\n'
                                'with Path("../external-calls").open("a") as log: log.write(sys.argv[1] + "\\n")\n'
                                f'sys.exit(19 if sys.argv[1] == "prepare" and {fault == "prepare"!r} else 0)\n')
                script = root / 'packages.sh'
                script.write_text(original.replace('/cache-scripts/external_packages.py', str(hook)))
                result = subprocess.run(['bash', str(script)], cwd=build / 'package', env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not fault, result.stderr)
                expected_calls = ['preflight', 'prepare'] if fault in ('', 'prepare') else ['preflight']
                self.assertEqual((build / 'external-calls').read_text().splitlines(), expected_calls)
                if not fault:
                    # Repeat import must remove its own old recipe/feed links too.
                    again = subprocess.run(['bash', str(script)], cwd=build / 'package', env=env,
                                           capture_output=True, text=True)
                    self.assertEqual(again.returncode, 0, again.stderr)
                    self.assertEqual((build / 'external-calls').read_text().splitlines(), expected_calls * 2)
                    rows = (build / '.custom-revisions.tsv').read_text().splitlines()
                    self.assertEqual(len(rows), 1)
                    name, url, actual = rows[0].split('\t')
                    self.assertEqual(name, 'yahuisme/packages')
                    self.assertEqual(actual, sha)
                    self.assertTrue(url)
                    for name in ('luci-app-homeproxy', 'sing-box'):
                        self.assertEqual((build / 'package' / name / 'Makefile').read_bytes(),
                                         (repo / name / 'Makefile').read_bytes())
                        self.assertFalse((build / 'feeds/luci' / name).is_symlink())
                else:
                    self.assertFalse((build / '.custom-revisions.tsv').exists())
                self.assertFalse(list(root.glob('mx4200-packages.*')))


if __name__ == '__main__':
    unittest.main()
