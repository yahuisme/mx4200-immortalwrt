#!/usr/bin/env python3
"""Validate and stage the exact MX4200 four-image release set."""
import json
import re
from pathlib import Path
import shutil


EXPECTED = {f'immortalwrt-qualcommax-ipq807x-linksys_{device}-squashfs-{kind}.bin'
            for device in ('mx4200v1', 'mx4200v2') for kind in ('factory', 'sysupgrade')}


def validate_images(directory):
    paths = [p for p in directory.glob('*.bin') if 'factory' in p.name or 'sysupgrade' in p.name]
    if len(paths) != 4 or any(p.is_symlink() or not p.is_file() or not p.stat().st_size for p in paths):
        raise ValueError('expected four nonempty images')
    if {p.name for p in paths} != EXPECTED:
        raise ValueError('unexpected MX4200 image filenames')


def stage(targets, output):
    directory = targets / 'qualcommax/ipq807x'
    selected = sorted(targets.rglob('*.bin'))
    # Other auxiliary binaries may exist, but never another factory/sysupgrade.
    selected = [p for p in selected if 'factory' in p.name or 'sysupgrade' in p.name]
    if len(selected) != 4 or {p.name for p in selected} != EXPECTED or any(
            p.parent != directory or p.is_symlink() or not p.is_file() or not p.stat().st_size for p in selected):
        raise ValueError('expected exactly four nonempty MX4200 v1/v2 factory/sysupgrade images')
    data = json.loads((directory / 'profiles.json').read_text())
    if data['target'] != 'qualcommax/ipq807x' or set(data['profiles']) != {'linksys_mx4200v1', 'linksys_mx4200v2'}:
        raise ValueError('unexpected target/profiles')
    if not re.fullmatch(r'r[0-9]+-[0-9a-f]+', data['version_code']):
        raise ValueError('unexpected version_code')
    for device, profile in data['profiles'].items():
        images = profile.get('images', [])
        expected = {f'immortalwrt-qualcommax-ipq807x-{device}-squashfs-{kind}.bin': kind
                    for kind in ('factory', 'sysupgrade')}
        if len(images) != 2 or {entry.get('name') for entry in images} != set(expected):
            raise ValueError('unexpected image metadata: ' + device)
        for entry in images:
            if (entry.get('type') != expected[entry['name']]
                    or entry.get('filesystem') != 'squashfs'
                    or entry.get('size') != (directory / entry['name']).stat().st_size):
                raise ValueError('image metadata differs from output: ' + entry['name'])
    output.mkdir()
    for path in selected:
        shutil.copyfile(path, output / path.name)
    validate_images(output)


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 4 or sys.argv[1] != 'stage':
        raise SystemExit('usage: release_images.py stage TARGETS OUTPUT')
    stage(Path(sys.argv[2]), Path(sys.argv[3]))
