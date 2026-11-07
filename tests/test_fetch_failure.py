"""Exercise the workflow's fetch/checkout/reset with an isolated real Git remote."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FetchFailureTests(unittest.TestCase):
    def test_each_build_fetches_current_master_and_records_exact_identity(self):
        lines = (ROOT / '.github/workflows/MX4200.yml').read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if 'SOURCE_REF="refs/heads/$REPO_REF"' in line)
        end = next(i for i in range(start, len(lines)) if 'git clean -ffdx' in lines[i])
        fragment = '\n'.join(line.strip() for line in lines[start:end + 1])
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, source, record = base / 'remote', base / 'source', base / 'record'
            record.mkdir()
            def git(path, *args):
                return subprocess.check_output(['git', '-C', str(path), *args], text=True,
                                               stderr=subprocess.DEVNULL).strip()
            remote.mkdir()
            git(remote, 'init', '-b', 'master')
            for index in (1, 2):
                (remote / 'tracked').write_text('upstream-' + str(index))
                git(remote, 'add', 'tracked')
                git(remote, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-m', 'upstream ' + str(index))
                expected = git(remote, 'rev-parse', 'HEAD')
                if index == 1:
                    subprocess.run(['git', 'clone', '-q', str(remote), str(source)], check=True)
                (source / 'tracked').write_text('old builder mutation')
                (source / 'old-patch').write_text('must not survive')
                result = subprocess.run(['bash', '-e', '-c', fragment.replace('/build-record/', str(record) + '/')],
                                        cwd=source, env=dict(os.environ, REPO_REF='master'),
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(git(source, 'rev-parse', 'HEAD'), expected)
                self.assertEqual((record / 'source-sha.txt').read_text().strip(), expected)
                self.assertEqual((record / 'source-ref.txt').read_text().strip(), 'master')
                self.assertEqual((source / 'tracked').read_text(), 'upstream-' + str(index))
                self.assertFalse((source / 'old-patch').exists())

    def test_shallow_r0_is_repaired_by_full_history_and_tracking_master(self):
        from revision_fixture import history, commit, git, revision
        from test_cache_workflow import step
        block = step('inputs')['run']
        fragment = block.split('SOURCE_REF="refs/heads/$REPO_REF"', 1)[1].split('mountpoint $DK_BIN', 1)[0]
        fragment = 'SOURCE_REF="refs/heads/$REPO_REF"' + fragment
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, source, record = base / 'remote', base / 'source', base / 'record'
            history(remote)
            commit(remote, 'one more official commit')
            record.mkdir()
            subprocess.run(['git', 'clone', '-q', '--depth=1', remote.as_uri(), str(source)], check=True)
            # The actual native script, not a synthetic rN response, reproduces r0.
            self.assertRegex(revision(source), r'^r0-[0-9a-f]+$')
            result = subprocess.run(['bash', '-e', '-c', fragment.replace('/build-record/', str(record) + '/')],
                                    cwd=source, env=dict(os.environ, REPO_REF='master'),
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git(source, 'rev-parse', '--is-shallow-repository'), 'false')
            self.assertEqual(git(source, 'rev-parse', '--abbrev-ref', 'HEAD'), 'master')
            self.assertEqual(git(source, 'rev-parse', '--abbrev-ref', '@{u}'), 'origin/master')
            self.assertEqual(revision(source), 'r2-' + git(source, 'rev-parse', '--short', 'HEAD'))
            self.assertEqual((record / 'source-revision.txt').read_text().strip(), revision(source))

    def test_source_revision_rejects_shallow_r0_and_untracked_local_history(self):
        from revision_fixture import history, git, revision
        from test_cache_workflow import step
        block = step('inputs')['run']
        fragment = block.split('SOURCE_REV=$(./scripts/getver.sh)', 1)[1].split('mountpoint $DK_BIN', 1)[0]
        fragment = 'SOURCE_REV=$(./scripts/getver.sh)' + fragment
        for shallow in (True, False):
            with self.subTest(shallow=shallow), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                remote, source = base / 'remote', base / 'source'
                history(remote)
                if shallow:
                    subprocess.run(['git', 'clone', '-q', '--depth=1', remote.as_uri(), str(source)], check=True)
                else:
                    source = remote  # Complete history without upstream yields r0+N.
                    self.assertRegex(revision(source), r'^r0\+[1-9][0-9]*-')
                result = subprocess.run(['bash', '-e', '-c', fragment.replace('/build-record/', str(base) + '/')],
                                        cwd=source, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Invalid official revision:', result.stdout)
                self.assertFalse((base / 'source-revision.txt').exists())

    def test_fetch_failure_stops_before_reset(self):
        lines = (ROOT / '.github/workflows/MX4200.yml').read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if 'SOURCE_REF="refs/heads/$REPO_REF"' in line)
        end = next(i for i in range(start, len(lines)) if 'git clean -ffdx' in lines[i])
        fragment = '\n'.join(line.strip() for line in lines[start:end + 1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT, text=True).strip()
            git('init', '-b', 'main')
            git('-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
                'commit', '--allow-empty', '-m', 'fixture')
            sha = git('rev-parse', 'HEAD')
            git('update-ref', 'refs/heads/master', sha)
            git('remote', 'add', 'origin', str(root / 'missing-remote'))
            tracked = root / 'tracked'
            tracked.write_text('original')
            git('add', 'tracked')
            git('-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
                'commit', '-m', 'local fixture')
            tracked.write_text('must survive failed fetch')
            head = git('rev-parse', 'HEAD')
            result = subprocess.run(['bash', '-e', '-c', fragment + '\nprintf CONTINUED'],
                                    cwd=root, env=dict(os.environ, REPO_REF='master', SOURCE_REF='refs/heads/master'),
                                    text=True, capture_output=True)
            self.assertIn('fatal:', result.stderr)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('CONTINUED', result.stdout)
            self.assertEqual(git('rev-parse', 'HEAD'), head)
            self.assertEqual(tracked.read_text(), 'must survive failed fetch')
