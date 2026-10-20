"""Real local clones and Actions-only evidence; no network or firmware build."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class BuildRecordTests(unittest.TestCase):
    def test_custom_revisions_survive_temporary_clone_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gitconfig = root / 'gitconfig'
            gitconfig.touch()
            env = dict(os.environ, GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM='1',
                       SOURCE_REVISIONS=str(root / 'sources.txt'), TMPDIR=str(root),
                       GITHUB_ENV=str(root / 'github-env'))
            revisions = {}
            for name, url in (
                ('luci-theme-aurora', 'https://github.com/eamonxg/luci-theme-aurora.git'),
                ('luci-app-aurora-config', 'https://github.com/eamonxg/luci-app-aurora-config.git'),
                ('packages', 'https://github.com/yahuisme/packages.git')):
                repo = root / name
                subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True, env=env)
                for package in ('luci-app-homeproxy', 'sing-box') if name == 'packages' else ('',):
                    path = repo / package / 'Makefile'
                    path.parent.mkdir(exist_ok=True)
                    path.write_text('# fixture\n')
                subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True, env=env)
                subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                                'commit', '-qm', 'fixture'], check=True, env=env)
                revisions['custom/' + name] = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], env=env, text=True).strip()
                subprocess.run(['git', 'config', '--global', f'url.{repo.as_uri()}.insteadOf', url], check=True, env=env)
            build = root / 'build'
            for name in ('package', 'feeds/luci', 'feeds/packages'):
                (build / name).mkdir(parents=True)
            result = subprocess.run(['bash', str(ROOT / 'scripts/packages.sh')], cwd=build / 'package',
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [line.split('\t') for line in (build / '.custom-revisions.tsv').read_text().splitlines()]
            recorded = {'custom/' + ('packages' if name == 'yahuisme/packages' else name): sha for name, url, sha in rows}
            self.assertEqual(recorded, revisions)
            self.assertTrue(all(url.startswith(('https://', 'file://')) for name, url, sha in rows))
            self.assertFalse((root / 'github-env').exists())
            self.assertFalse(list(root.glob('tmp.*')))
            for name in ('luci-theme-aurora', 'luci-app-aurora-config', 'luci-app-homeproxy', 'sing-box'):
                self.assertTrue((build / 'package' / name / 'Makefile').is_file())
