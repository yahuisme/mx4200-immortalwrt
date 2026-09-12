#!/usr/bin/env python3
"""Publish MX4200 firmware under the workflow's repository-wide concurrency lock."""
import json
import os
import re
import subprocess
from pathlib import Path
import sys


def gh(*args, token=None):
    env = dict(os.environ, GH_TOKEN=token) if token else None
    return subprocess.check_output(['gh', *args], text=True, env=env)


def main(tree):
    repo = os.environ['GITHUB_REPOSITORY']
    sha = os.environ['GITHUB_SHA']
    if os.environ['GITHUB_REF'] != 'refs/heads/main':
        return
    def current():
        return json.loads(gh('api', f'repos/{repo}/commits/main'))['sha'] == sha

    if not current():
        print('Skip release: build SHA is no longer main HEAD.')
        return
    tag = os.environ['WRT_RELEASE_NAME']
    number = int(os.environ['GITHUB_RUN_NUMBER'])
    run = json.loads(gh('api', f'repos/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]}',
                        token=os.environ.get('GH_READ_TOKEN')))
    pattern = r'MX4200_ImmortalWrt_v[0-9.]+(?:-rc[0-9]+)?_r[0-9]+_\d{2}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}'
    if not re.fullmatch(pattern, tag):
        raise ValueError(f'Unexpected release name: {tag}')
    pages = json.loads(gh('api', f'repos/{repo}/releases?per_page=100', '--paginate', '--slurp'))
    releases = [release for page in pages for release in page]
    old = []
    for release in releases:
        name = release['tag_name']
        if name == tag:
            print('Skip release: name already exists (including same-second builds).')
            return
        if not re.fullmatch(pattern, name) or release['draft'] or release['prerelease']:
            continue
        marker = re.search(r'^MX4200 build run: `([0-9]+)`$', release.get('body') or '', re.M)
        # Run numbers order same-SHA builds independently of completion order.
        # Legacy releases have no marker: only publications before this run are safe.
        older = (int(marker[1]) < number if marker else
                 bool(release['published_at'] and release['published_at'] < run['created_at']))
        if not older:
            print('Skip release: an equal, newer or unorderable product already exists.')
            return
        old.append(name)
    refs = json.loads(gh('api', f'repos/{repo}/git/matching-refs/tags/{tag}'))
    if any(ref['ref'] == f'refs/tags/{tag}' for ref in refs):
        raise ValueError('Release tag already exists; refusing to reuse or move it')
    images = sorted((tree / 'upload').glob('*.bin'))
    if len(images) != 4 or any(p.stat().st_size == 0 for p in images):
        raise ValueError('Expected exactly four nonempty bin images')
    notes = tree / 'release-notes.md'
    notes.write_text(notes.read_text() + f'\nMX4200 build run: `{number}`\n')
    if not current():
        print('Skip release: main advanced before upload.')
        return
    gh('release', 'create', tag, *map(str, images), '-R', repo, '--target', sha,
       '--title', tag, '--notes-file', str(notes), '--draft', '--latest=false')

    def verify(draft):
        release = json.loads(gh('release', 'view', tag, '-R', repo,
                                '--json', 'tagName,isDraft,assets'))
        assets = {asset['name']: asset['size'] for asset in release['assets']}
        expected = {p.name: p.stat().st_size for p in images}
        if release['tagName'] != tag or release['isDraft'] != draft or assets != expected:
            raise ValueError('Release state or uploaded images do not match')

    verify(True)
    if not current():
        print('Main advanced during upload; leave draft for inspection, do not prune.')
        return
    gh('release', 'edit', tag, '-R', repo, '--draft=false', '--latest')
    verify(False)
    # Snapshot only: never re-list and accidentally collect a later publication.
    for name in old:
        if not current():
            print('Main advanced; stop pruning.')
            return
        gh('release', 'delete', name, '-R', repo, '--cleanup-tag', '--yes')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
