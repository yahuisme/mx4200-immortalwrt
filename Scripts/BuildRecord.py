#!/usr/bin/env python3
"""Actions-only build evidence and fail-closed Release asset readback."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
from urllib.parse import quote


def images(directory):
    paths = sorted(directory.glob('*.bin'))
    if len(paths) != 4 or any(not p.stat().st_size for p in paths):
        raise ValueError('expected four nonempty images')
    for device in ('mx4200v1', 'mx4200v2'):
        for kind in ('factory', 'sysupgrade'):
            if len(list(directory.glob(f'*linksys_{device}-*{kind}.bin'))) != 1:
                raise ValueError(f'missing or duplicate {device} {kind}')
    result = []
    for path in paths:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result.append(dict(name=path.name, size=path.stat().st_size, digest='sha256:' + digest))
    return result


CUSTOM_REVISIONS = {
    'luci-theme-aurora': 'CUSTOM_THEME_SHA',
    'luci-app-aurora-config': 'CUSTOM_CONFIG_SHA',
    'packages': 'CUSTOM_PACKAGES_SHA',
}


def revision(path):
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()


def validate_revisions(root):
    recorded = {}
    for line in (root / 'source-revisions.txt').read_text().splitlines():
        fields = line.split()
        if len(fields) != 2 or not re.fullmatch(r'[0-9a-f]{40}', fields[1]):
            raise ValueError('malformed source revision: ' + line)
        name, sha = fields
        if name in recorded:
            raise ValueError('duplicate source revision: ' + name)
        recorded[name] = sha
    expected = {'source': revision(root), 'recipe': revision(Path(__file__).resolve().parents[1])}
    for feed in sorted((root / 'feeds').iterdir()):
        # feeds also contains generated index/*.tmp directories, not checkouts.
        if (feed / '.git').exists():
            expected['feeds/' + feed.name] = revision(feed)
    for name, variable in CUSTOM_REVISIONS.items():
        sha = os.environ.get(variable, '')
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('missing actual custom revision: ' + name)
        expected['custom/' + name] = sha
    if recorded != expected:
        raise ValueError('source revisions differ from actual source/recipe/feeds/custom checkouts')


def collect(root, output):
    validate_revisions(root)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / '.config', output / 'final.config')
    shutil.copy2(root / 'source-revisions.txt', output / 'source-revisions.txt')
    manifests = sorted((root / 'bin/targets').rglob('*.manifest'))
    if not manifests:
        raise ValueError('package manifests missing')
    for path in manifests:
        target = output / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (output / 'images.json').write_text(json.dumps(images(root / 'upload'), indent=2) + '\n')
    environment = {key: os.environ.get(key, '') for key in (
        'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
        'RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')}
    environment['uname'] = subprocess.check_output(['uname', '-a'], text=True).strip()
    environment['os-release'] = Path('/etc/os-release').read_text()
    environment['packages'] = subprocess.check_output(
        ['dpkg-query', '-W', '-f=${Package}\t${Version}\n'], text=True)
    (output / 'environment.json').write_text(json.dumps(environment, indent=2) + '\n')


def verify(directory, repository, tag):
    expected = {a['name']: a for a in images(directory)}
    release = json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{repository}/releases/tags/{quote(tag, safe="")}'], text=True))
    if release['tag_name'] != tag or release['draft'] or release['prerelease']:
        raise ValueError('unexpected Release identity/state')
    assets = release['assets']
    if len(assets) != 4 or {a['name'] for a in assets} != set(expected):
        raise ValueError('Release asset names/count differ from staged images')
    for asset in assets:
        local = expected[asset['name']]
        if asset['state'] != 'uploaded' or asset['size'] != local['size']:
            raise ValueError(f'asset state/size mismatch: {asset["name"]}')
        if asset.get('digest'):
            if asset['digest'] != local['digest']:
                raise ValueError(f'asset digest mismatch: {asset["name"]}')
        else:
            with subprocess.Popen(['gh', 'api', f'repos/{repository}/releases/assets/{asset["id"]}',
                                   '-H', 'Accept: application/octet-stream'], stdout=subprocess.PIPE) as proc:
                stream = proc.stdout
                assert stream is not None
                downloaded = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    downloaded.update(chunk)
                actual = 'sha256:' + downloaded.hexdigest()
                if proc.wait() or actual != local['digest']:
                    raise ValueError('Release asset download mismatch: ' + asset['name'])
    print('Verified four uploaded Release images: names, sizes and SHA-256')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    record = commands.add_parser('collect')
    record.add_argument('root', type=Path)
    record.add_argument('output', type=Path)
    check = commands.add_parser('verify')
    check.add_argument('directory', type=Path)
    check.add_argument('repository')
    check.add_argument('tag')
    args = parser.parse_args()
    if args.command == 'collect':
        collect(args.root, args.output)
    else:
        verify(args.directory, args.repository, args.tag)
