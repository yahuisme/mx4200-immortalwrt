#!/usr/bin/env python3
"""Load the checked-in build contract shared by CI helpers."""
import json
import os
from pathlib import Path
import re


def load(profile=None):
    # Runner helpers use the checked-out profile, even when DK_PROFILE names
    # a container-only mount. In /cache-scripts that checkout is absent, so
    # container helpers use the explicitly mounted DK_PROFILE instead.
    profile = Path(profile or os.environ.get('DK_PROFILE') or Path(__file__).resolve().parents[1] / 'user/default')
    if not (profile / 'build.json').is_file() and os.environ.get('DK_PROFILE'):
        profile = Path(os.environ['DK_PROFILE'])
    data = json.loads((profile / 'build.json').read_text())
    if data['system'] not in ('openwrt', 'immortalwrt') or data['device'] not in ('W1700K', 'MX4200'):
        raise ValueError('unsupported build system/device')
    if not re.fullmatch(r'[a-z0-9_]+/[a-z0-9_]+', data['target']):
        raise ValueError('invalid target')
    if not data['images'] or len(set(data['images'])) != len(data['images']):
        raise ValueError('missing or duplicate release images')
    for name in data['images']:
        if Path(name).name != name or not name.startswith(data['system'] + '-'):
            raise ValueError('invalid release image name')
    if set(data['cache_prefix']) != {'tc', 'cc', 'dl'} or any(not v for v in data['cache_prefix'].values()):
        raise ValueError('incomplete cache namespaces')
    external = data.get('external_images', [])
    official_name = f"{data['system']}-{data['target'].replace('/', '-')}-linksys_homewrk-initramfs-uImage.itb"
    if external and (external != [official_name] or official_name not in data['images']):
        raise ValueError('invalid external firmware attachment')
    if 'release_groups' in data:
        names, boards = [], []
        for key, group in data['release_groups'].items():
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', key):
                raise ValueError('invalid release group')
            if not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*', group['device']):
                raise ValueError('invalid release device')
            profiles, images = group['profiles'], group['images']
            if not profiles or not images or any(not re.fullmatch(r'linksys_[a-z0-9]+', p) for p in profiles):
                raise ValueError('invalid release profiles/images')
            # Each native profile supplies exactly its own factory/sysupgrade pair.
            expected = {f"{data['system']}-{data['target'].replace('/', '-')}-{board}-squashfs-{kind}.{extension}"
                        for board in profiles for kind, extension in
                        (('factory', 'ubi' if board == 'linksys_homewrk' else 'bin'), ('sysupgrade', 'bin'))}
            if 'linksys_homewrk' in profiles:
                expected.add(f"{data['system']}-{data['target'].replace('/', '-')}-linksys_homewrk-initramfs-uImage.itb")
            if len(images) != len(expected) or set(images) != expected:
                raise ValueError('release images differ from native profiles')
            names.extend(images)
            boards.extend(profiles)
        if (len(names) != len(set(names)) or set(names) != set(data['images'])
                or len(boards) != len(set(boards))):
            raise ValueError('release groups must partition images and profiles')
    return data
