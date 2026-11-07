#!/usr/bin/env python3
"""Check the separate RAM build uses pristine official objects and minimal intent."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def verify(root, main, record):
    root, main = Path(root), Path(main)
    sha = git(root, 'rev-parse', '--verify', 'HEAD')
    if sha != git(main, 'rev-parse', '--verify', 'HEAD'):
        raise ValueError('RAM and main official source identities differ')
    if git(root, 'remote', 'get-url', 'origin') != 'https://github.com/immortalwrt/immortalwrt.git':
        raise ValueError('RAM source is not the official origin')
    if git(root, 'diff', 'HEAD', '--'):
        raise ValueError('RAM official tracked sources were modified')
    for name in ('files', '.external-packages', '.external-packages.mk', '.custom-revisions.tsv'):
        if (root / name).exists() or (root / name).is_symlink():
            raise ValueError('Project customization leaked into RAM source: ' + name)
    recipe = Path(__file__).resolve().parents[1] / 'user/ramboot/config.diff'
    if not recipe.is_file():
        recipe = Path('/bld/user/ramboot/config.diff')
    expected = {
        'CONFIG_TARGET_qualcommax': 'y',
        'CONFIG_TARGET_qualcommax_ipq807x': 'y',
        'CONFIG_TARGET_qualcommax_ipq807x_DEVICE_linksys_homewrk': 'y',
        'CONFIG_TARGET_ROOTFS_INITRAMFS': 'y',
        'CONFIG_PACKAGE_luci': 'y',
        'CONFIG_LUCI_LANG_zh_Hans': 'y',
    }
    requested = dict(line.split('=', 1) for line in recipe.read_text().splitlines()
                     if line.startswith('CONFIG_'))
    if requested != expected:
        raise ValueError('RAM profile must add only Chinese LuCI to official HomeWRK')
    config = dict(line.split('=', 1) for line in (root / '.config').read_text().splitlines()
                  if line.startswith('CONFIG_') and '=' in line)
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError('RAM final config lost requested HomeWRK/LuCI symbols')
    feeds = []
    for row in (root / 'feeds.conf').read_text().splitlines():
        parts = row.split()
        if not parts or parts[0] not in ('src-git', 'src-git-full'):
            continue
        name = parts[1]
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Invalid official feed name')
        feed = root / 'feeds' / name
        main_feed = main / 'feeds' / name
        commit = git(feed, 'rev-parse', '--verify', 'HEAD')
        if commit != git(main_feed, 'rev-parse', '--verify', 'HEAD') or git(feed, 'diff', 'HEAD', '--'):
            raise ValueError('RAM feed is not pristine matching official objects: ' + name)
        feeds.append(dict(name=name, sha=commit))
    if not feeds:
        raise ValueError('No official RAM feeds')
    revision = subprocess.check_output([str(root / 'scripts/getver.sh')], cwd=root, text=True).strip()
    if not re.fullmatch(r'r[1-9][0-9]*-[0-9a-f]+', revision):
        raise ValueError('RAM official revision is not a nonzero native revision: ' + revision)
    result = dict(source_sha=sha, revision=revision, feeds=feeds,
                  config_sha256=hashlib.sha256((root / '.config').read_bytes()).hexdigest(),
                  pristine=True, customization='Chinese LuCI only')
    Path(record).write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('main_source', type=Path)
    parser.add_argument('record', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.source, args.main_source, args.record)))
