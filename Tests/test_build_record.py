"""Real local clones and Actions-only evidence; no network or firmware build."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from Scripts import BuildRecord
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def source_fixture(root):
    expected = {'recipe': BuildRecord.revision(ROOT)}
    for name in ('source', 'feeds/packages', 'feeds/luci', 'feeds/extra-fixture'):
        path = root if name == 'source' else root / name
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', str(path)], check=True)
        subprocess.run(['git', '-C', str(path), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit',
                        '--allow-empty', '-qm', name], check=True)
        expected[name] = BuildRecord.revision(path)
    (root / 'feeds/packages.tmp').mkdir()
    (root / 'feeds/packages.index').touch()
    env = {}
    for index, (name, variable) in enumerate(BuildRecord.CUSTOM_REVISIONS.items(), 1):
        expected['custom/' + name] = env[variable] = str(index) * 40
    (root / 'source-revisions.txt').write_text(''.join(f'{k} {v}\n' for k, v in expected.items()))
    return env


class BuildRecordTests(unittest.TestCase):
    def test_incomplete_or_wrong_records_fail_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = source_fixture(root)
            path = root / 'source-revisions.txt'
            valid = path.read_text()
            with patch.dict(os.environ, env):
                BuildRecord.validate_revisions(root)
                for line in valid.splitlines(keepends=True):
                    for replacement in ('', line.split()[0] + ' ' + 'f' * 40 + '\n'):
                        with self.subTest(line=line, replacement=replacement):
                            path.write_text(valid.replace(line, replacement))
                            with self.assertRaises(ValueError):
                                BuildRecord.collect(root, root / 'record')
                            self.assertFalse((root / 'record').exists())
                for bad in ('', 'source not-a-sha\n', valid + valid.splitlines()[0] + '\n'):
                    path.write_text(bad)
                    with self.assertRaises(ValueError):
                        BuildRecord.validate_revisions(root)
                path.write_text(valid)
                with patch.dict(os.environ, {next(iter(env)): ''}):
                    with self.assertRaisesRegex(ValueError, 'missing actual custom'):
                        BuildRecord.validate_revisions(root)

    def test_collect_exact_inputs_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.config').write_text('CONFIG_FIXTURE=y\n')
            env = source_fixture(root)
            manifests = root / 'bin/targets/qualcommax/ipq807x'
            manifests.mkdir(parents=True)
            (manifests / 'fixture.manifest').write_text('fixture - 1\n')
            (root / 'upload').mkdir()
            for device in ('mx4200v1', 'mx4200v2'):
                for kind in ('factory', 'sysupgrade'):
                    (root / 'upload' / f'fixture-linksys_{device}-{kind}.bin').write_bytes(b'fixture')
            result = subprocess.run(['python3', str(ROOT / 'Scripts/BuildRecord.py'), 'collect',
                                     str(root), str(root / 'record')], capture_output=True, text=True,
                                    env=dict(os.environ, **env, GH_TOKEN='must-not-be-recorded'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'record/final.config').read_bytes(), (root / '.config').read_bytes())
            self.assertEqual((root / 'record/source-revisions.txt').read_bytes(),
                             (root / 'source-revisions.txt').read_bytes())
            self.assertEqual((root / 'record/bin/targets/qualcommax/ipq807x/fixture.manifest').read_text(), 'fixture - 1\n')
            assets = json.loads((root / 'record/images.json').read_text())
            self.assertEqual(len(assets), 4)
            self.assertTrue(all(a['digest'] == 'sha256:' + hashlib.sha256(b'fixture').hexdigest() for a in assets))
            environment = (root / 'record/environment.json').read_text()
            self.assertNotIn('must-not-be-recorded', environment)
            self.assertIn('packages', json.loads(environment))
            self.assertFalse(list((root / 'record').rglob('*.bin')))

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
            result = subprocess.run(['bash', str(ROOT / 'Scripts/Packages.sh')], cwd=build / 'package',
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = dict(line.split() for line in (root / 'sources.txt').read_text().splitlines())
            self.assertEqual(recorded, revisions)
            retained = dict(line.split('=', 1) for line in (root / 'github-env').read_text().splitlines())
            self.assertEqual(retained, {variable: revisions['custom/' + name]
                                       for name, variable in BuildRecord.CUSTOM_REVISIONS.items()})
            self.assertFalse(list(root.glob('tmp.*')))
            for name in ('luci-theme-aurora', 'luci-app-aurora-config', 'luci-app-homeproxy', 'sing-box'):
                self.assertTrue((build / 'package' / name / 'Makefile').is_file())
