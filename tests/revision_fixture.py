"""Real Git history with the reviewed official getver, rebased at fixture root."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
    return subprocess.check_output(['git', '-C', str(root), *args], env=env,
                                   stderr=subprocess.DEVNULL, text=True).strip()


def commit(root, message):
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '--allow-empty', '-m', message)
    return git(root, 'rev-parse', 'HEAD')


def history(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    git(root, 'init', '-b', 'master')
    baseline = commit(root, 'fixture reboot boundary')
    scripts = root / 'scripts'
    scripts.mkdir(exist_ok=True)
    reviewed = ROOT / 'tests/fixtures/snapshot-source/scripts/getver.sh'
    text = reviewed.read_text()
    assert text.count('REBOOT=ee53a240ac902dc83209008a2671e7fdcf55957a') == 1
    getver = scripts / 'getver.sh'
    getver.write_text(text.replace('REBOOT=ee53a240ac902dc83209008a2671e7fdcf55957a',
                                  'REBOOT=' + baseline))
    getver.chmod(0o755)
    commit(root, 'official getver with local history boundary')
    return baseline


def revision(root):
    return subprocess.check_output(['./scripts/getver.sh'], cwd=root, text=True).strip()
