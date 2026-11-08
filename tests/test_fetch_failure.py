"""Exercise latest-stable resolution/fetch/reset using isolated real Git remotes."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

from revision_fixture import history, commit, git, revision
from test_cache_workflow import step

ROOT = Path(__file__).resolve().parents[1]
STABLE_REVISION = 'r19780-a1b2c3d4e5'


def stable_history(root, version=STABLE_REVISION):
    """Keep native getver; stable releases carry their authoritative version file."""
    history(root)
    (root / 'version').write_text(version + '\n')
    return commit(root, 'stable release with native version file')


def resolver_boundary(base):
    """Private python3 boundary: only the official resolver is replaced, no network."""
    bindir = base / 'private-bin'
    bindir.mkdir()
    wrapper = bindir / 'python3'
    wrapper.write_text(f'''#!{sys.executable}
import json
import os
import sys
from pathlib import Path
if sys.argv[1] == '/cache-scripts/official_release.py':
    with open(os.environ['RESOLVER_LOG'], 'a') as log:
        log.write(' '.join(sys.argv[1:]) + '\\n')
    if os.environ.get('RESOLVER_FAIL'):
        sys.exit(23)
    tag = Path(os.environ['RESOLVER_TAG_FILE']).read_text().strip()
    Path(sys.argv[2]).write_text(json.dumps({{'version': tag.removeprefix('v'), 'tag': tag}}))
    print(tag)
else:
    os.execv({sys.executable!r}, [{sys.executable!r}] + sys.argv[1:])
''')
    wrapper.chmod(0o755)
    tagfile = base / 'resolved-tag'
    tagfile.write_text('v25.12.2\n')
    return dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                REPO_REF='latest-release', RESOLVER_TAG_FILE=str(tagfile),
                RESOLVER_LOG=str(base / 'resolver-calls'),
                GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')


def source_fragment(record, *, include_revision=True):
    block = step('inputs')['run']
    start = block.index('SOURCE_TAG=$(python3 /cache-scripts/official_release.py ')
    end_marker = 'mountpoint $DK_BIN' if include_revision else 'git clean -ffdx'
    end = block.index(end_marker, start)
    if not include_revision:
        end += len(end_marker)
    return block[start:end].replace('/build-record/', str(record) + '/')


class FetchFailureTests(unittest.TestCase):
    def test_each_build_fetches_latest_stable_tag_and_records_exact_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, source, record = base / 'remote', base / 'source', base / 'record'
            record.mkdir()
            stable_history(remote)
            env = resolver_boundary(base)
            for index, tag in enumerate(('v25.12.2', 'v25.12.3'), 1):
                with self.subTest(tag=tag):
                    (remote / 'tracked').write_text('upstream-' + str(index))
                    expected = commit(remote, 'upstream stable ' + tag)
                    git(remote, 'tag', tag)
                    if index == 1:
                        subprocess.run(['git', 'clone', '-q', '--depth=1', remote.as_uri(), str(source)], check=True)
                    else:
                        self.assertNotEqual(git(source, 'rev-parse', 'HEAD'), expected)
                        absent = subprocess.run(['git', '-C', str(source), 'rev-parse', '--verify', 'refs/tags/' + tag],
                                                capture_output=True)
                        self.assertNotEqual(absent.returncode, 0)
                    Path(env['RESOLVER_TAG_FILE']).write_text(tag + '\n')
                    (source / 'tracked').write_text('old builder mutation')
                    (source / 'old-patch').write_text('must not survive')
                    result = subprocess.run(['bash', '-e', '-c', source_fragment(record)],
                                            cwd=source, env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(git(source, 'rev-parse', 'HEAD'), expected)
                    self.assertEqual(git(source, 'rev-parse', '--abbrev-ref', 'HEAD'), 'HEAD')
                    self.assertEqual(git(source, 'rev-parse', '--is-shallow-repository'), 'true')
                    for field, value in (('tag', tag), ('ref', 'refs/tags/' + tag), ('sha', expected),
                                         ('revision', STABLE_REVISION)):
                        self.assertEqual((record / ('source-' + field + '.txt')).read_text().strip(), value)
                    self.assertEqual((source / 'tracked').read_text(), 'upstream-' + str(index))
                    self.assertFalse((source / 'old-patch').exists())
            calls = Path(env['RESOLVER_LOG']).read_text().splitlines()
            self.assertEqual(calls, ['/cache-scripts/official_release.py ' + str(record / 'official-release.json')] * 2)

    def test_shallow_detached_stable_version_file_is_authoritative(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, source, record = base / 'remote', base / 'source', base / 'record'
            record.mkdir()
            stable_history(remote)
            git(remote, 'tag', 'v25.12.2')
            subprocess.run(['git', 'clone', '-q', '--depth=1', remote.as_uri(), str(source)], check=True)
            result = subprocess.run(['bash', '-e', '-c', source_fragment(record)], cwd=source,
                                    env=resolver_boundary(base), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(revision(source), STABLE_REVISION)
            self.assertNotIn(git(source, 'rev-parse', '--short', 'HEAD'), STABLE_REVISION)
            self.assertEqual((record / 'source-revision.txt').read_text().strip(), STABLE_REVISION)
            # Native getver falls back to r0 without the release's version file.
            (source / 'version').unlink()
            self.assertRegex(revision(source), r'^r0-[0-9a-f]+$')

    def test_source_revision_rejects_invalid_stable_version(self):
        block = step('inputs')['run']
        fragment = 'SOURCE_REV=$(./scripts/getver.sh)' + block.split('SOURCE_REV=$(./scripts/getver.sh)', 1)[1].split('mountpoint $DK_BIN', 1)[0]
        for value in ('r0-deadbeef', 'r0+2-deadbeef', 'unknown', 'r123-nothex'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                stable_history(base, value)
                result = subprocess.run(['bash', '-e', '-c', fragment.replace('/build-record/', str(base) + '/')],
                                        cwd=base, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Invalid official revision:', result.stdout)
                self.assertFalse((base / 'source-revision.txt').exists())

    def test_fetch_failure_stops_before_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, record = base / 'source', base / 'record'
            record.mkdir()
            stable_history(source)
            git(source, 'remote', 'add', 'origin', str(base / 'missing-remote'))
            tracked = source / 'tracked'
            tracked.write_text('original')
            commit(source, 'local fixture')
            tracked.write_text('must survive failed fetch')
            (source / 'old-patch').write_text('must also survive failed fetch')
            head = git(source, 'rev-parse', 'HEAD')
            result = subprocess.run(['bash', '-e', '-c', source_fragment(record) + '\nprintf CONTINUED'],
                                    cwd=source, env=resolver_boundary(base), text=True, capture_output=True)
            self.assertIn('fatal:', result.stderr)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('CONTINUED', result.stdout)
            self.assertEqual(git(source, 'rev-parse', 'HEAD'), head)
            self.assertEqual(tracked.read_text(), 'must survive failed fetch')
            self.assertTrue((source / 'old-patch').exists())
            self.assertFalse((record / 'source-sha.txt').exists())

    def test_resolver_failure_or_non_numeric_tag_stops_before_fetch(self):
        for tag in ('v25.12.2-rc1', 'master', 'v25.12', 'v25.12.2;false', 'resolver-fails'):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                source, record = base / 'source', base / 'record'
                record.mkdir()
                stable_history(source)
                head = git(source, 'rev-parse', 'HEAD')
                env = resolver_boundary(base)
                Path(env['RESOLVER_TAG_FILE']).write_text(tag + '\n')
                if tag == 'resolver-fails':
                    env['RESOLVER_FAIL'] = '1'
                # No origin exists: reaching fetch would expose a fatal Git error.
                result = subprocess.run(['bash', '-e', '-c', source_fragment(record)],
                                        cwd=source, env=env, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('fatal:', result.stderr)
                if tag != 'resolver-fails':
                    self.assertIn('No stable release tag found', result.stdout)
                self.assertEqual(git(source, 'rev-parse', 'HEAD'), head)
                self.assertFalse((record / 'source-sha.txt').exists())
