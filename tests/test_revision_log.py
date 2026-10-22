"""Source/feed revision logging and fail-closed preparation."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import render, step

class RevisionLogTests(unittest.TestCase):
    def test_nested_prepare_logs_and_failures(self):
        block = render(step('inputs')['run'], {})
        for phase in ('', 'fetch', 'git-access', 'feed-revision', 'update', 'install', 'custom', 'go-floor', 'defconfig', 'defaults'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                source = base / 'source'
                (source / 'scripts').mkdir(parents=True)
                (base / 'build-record').mkdir()
                profile = base / 'profile'
                (profile / 'tree').mkdir(parents=True)
                (profile / 'files').mkdir()
                (source / 'feeds/luci/.git').mkdir(parents=True)
                (profile / 'settings.ini').write_text('REPO_URL=https://github.com/immortalwrt/immortalwrt\nREPO_REF=latest-release\n')
                (source / 'feeds.conf.default').write_text('# fixture\n')
                (profile / 'config.diff').write_text('CONFIG_TEST=y\n')
                (profile / 'custom.sh').write_text('[ "$FAIL" != custom ] || exit 19\n')
                feeds = source / 'scripts/feeds'
                feeds.write_text('#!/bin/bash\nprintf "feeds %s\\n" "$*" >> "$LOG"\n'
                                 '[ "$1" != "$FAIL" ] || exit 19\n'
                                 'if [ "$*" = "list -s" ]; then printf "luci src-git %s fixture-url\\n" "$FEED_SHA"; fi\n')
                feeds.chmod(0o755)
                env = dict(os.environ, DK_OPENWRT=str(source), DK_BIN=str(base / 'bin'),
                           DK_PROFILE=str(profile), GITHUB_OUTPUT=str(base / 'output'),
                           BUILDER_FINGERPRINT='fixture-builder', LOG=str(base / 'calls'), FAIL=phase,
                           SOURCE_SHA='1' * 40, FEED_SHA='2' * 40)
                stub = '''
                docker_exec() { shift; "$@"; }
                git() {
                  printf 'git %s\\n' "$*" >> "$LOG"
                  if [ "$1" = ls-remote ]; then
                    [ "$FAIL" != fetch ] || return 19
                    printf '1 refs/tags/v25.12.2\\n'
                    return 0
                  fi
                  [ "$1" != "$FAIL" ] || return 19
                  if [ "$*" = 'rev-parse --verify HEAD' ]; then
                    [ "$FAIL" != git-access ] || return 19
                  fi
                  if [ "$*" = 'rev-parse --verify HEAD' ]; then
                    printf '%s\\n' "$SOURCE_SHA"
                  fi
                  if [ "$1" = -C ]; then
                    [ "$FAIL" != feed-revision ] || return 19
                    printf '%s\\n' "$FEED_SHA"
                  fi
                }
                mountpoint() { :; }
                make() { [ "$1" != "$FAIL" ] || return 19; }
                python3() {
                  case "$1" in
                    */check_go.py) [ "$FAIL" != go-floor ] || return 19;;
                    */check_defaults.py) [ "$FAIL" != defaults ] || return 19;;
                    */cache.py) printf 'key\\n' >> "$LOG"; printf 'fixture-key\\n';;
                    *) return 99;;
                  esac
                }
                export -f git mountpoint make python3
                '''
                phase_block = block.replace('/build-record/source-tag.txt', str(base / 'build-record/source-tag.txt'))
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', stub + phase_block],
                                        cwd=base, env=env, text=True, capture_output=True)
                expected = 1 if phase in ('fetch', 'update', 'install') else (19 if phase else 0)
                self.assertEqual(result.returncode, expected, result.stderr)
                calls = (base / 'calls').read_text()
                if phase:
                    self.assertNotIn('\nkey\n', '\n' + calls)
                    self.assertFalse((base / 'output').exists())
                else:
                    self.assertIn(env['SOURCE_SHA'], result.stdout)
                    self.assertIn('Feed luci: ' + env['FEED_SHA'], result.stdout)
                    self.assertEqual((source / '.config').read_text(), 'CONFIG_TEST=y\nCONFIG_CCACHE_DIR="/ghcache"\n')
                    self.assertEqual((profile / 'config.diff').read_text(), 'CONFIG_TEST=y\n')
                    self.assertEqual((base / 'output').read_text(), 'key=tc-v1-mx4200-arm64-fixture-key\n')

    def test_actual_checkout_revisions(self):
        block = step('Prepare source and cache key')['run']
        self.assertIn('# Log actual source/feed revisions', block)
        block = block.split('# Log actual source/feed revisions', 1)[1].split('\n', 1)[1].split('make defconfig', 1)[0]
        paths = ['.', 'feeds/luci', 'feeds/packages']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = {}
            for index, path in enumerate(paths):
                local = root / (path.lstrip('/') if path.startswith('/') else path)
                local.mkdir(parents=True, exist_ok=True)
                def git(*args):
                    return subprocess.check_output(['git', '-C', str(local), *args], stderr=subprocess.DEVNULL, text=True).strip()
                git('init')
                git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '--allow-empty', '-m', f'input {index}')
                expected[path] = git('rev-parse', 'HEAD')
            block = block.replace('/tmp/yahuisme-packages', str(root / 'tmp/yahuisme-packages'))
            result = subprocess.run(['bash', '-e', '-c', render(block, {})], cwd=root,
                                    env=dict(os.environ, REPO_REF='latest-release', REPO_URL='fixture-url'), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for sha in expected.values():
                self.assertEqual(result.stdout.count(sha), 1, result.stdout)
            self.assertIn('Source fixture-url/latest-release:', result.stdout)
            self.assertNotIn('Donor ', result.stdout)
            self.assertEqual(len(result.stdout.splitlines()), len(paths))
            self.assertFalse((root / 'source-revisions.txt').exists())
            # Production provenance reads the actual Git trees, never a duplicate log file.
            import json
            from test_record_contract import RecordContract
            record_root = root / 'record-fixture'
            fixture = RecordContract()
            fixture.fixture(record_root)
            result = fixture.run_record(record_root)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads((record_root / 'record/build.json').read_text())
            for item, path in [(record['source'], record_root),
                               (record['feeds'][0], record_root / 'feeds/packages')]:
                actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--verify', 'HEAD'], text=True).strip()
                self.assertEqual(item['sha'], actual)
            self.assertFalse((record_root / 'source-revisions.txt').exists())
            self.assertEqual(list(root.glob('*.lock')), [])
