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
                         {'luci-app-advanced-reboot.json', 'luci-app-ttyd.json'})

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
                hook = root / 'external.py'
                hook.write_text('import sys\nsys.exit(' + ('19' if fault == 'prepare' else '0') + ')\n')
                script = root / 'packages.sh'
                script.write_text(original.replace('/cache-scripts/external_packages.py', str(hook)))
                result = subprocess.run(['bash', str(script)], cwd=build / 'package', env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not fault, result.stderr)
                if not fault:
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
