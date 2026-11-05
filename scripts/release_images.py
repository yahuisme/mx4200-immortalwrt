#!/usr/bin/env python3
"""Validate native Linksys image metadata, then stage disjoint Release groups."""
import json
import re
from pathlib import Path
import shutil
import sys

try:
    from .build_profile import load
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_profile import load


PROFILE = Path(__file__).resolve().parents[1] / 'user/default'


def image_paths(directory, recursive=False):
    paths = directory.rglob('*') if recursive else directory.iterdir()
    return [p for p in paths if (p.suffix in ('.bin', '.ubi')
            and ('factory' in p.name or 'sysupgrade' in p.name))
            or p.name.endswith('sysupgrade.itb')]


def validate_images(directory, names):
    paths = image_paths(directory)
    if len(paths) != len(names) or {p.name for p in paths} != set(names) or any(
            p.is_symlink() or not p.is_file() or not p.stat().st_size for p in paths):
        raise ValueError('unexpected, missing, empty or symlink release images')


def stage(targets, output, group=None):
    contract = load(PROFILE)
    groups = contract['release_groups']
    if group is not None:
        groups = {group: groups[group]}
    names = {name for item in groups.values() for name in item['images']}
    boards = {board for item in groups.values() for board in item['profiles']}
    directory = targets / contract['target']
    selected = image_paths(targets, recursive=True)
    # Auxiliary binaries are allowed, but never another target's flash image.
    if len(selected) != len(names) or {p.name for p in selected} != names or any(
            p.parent != directory or p.is_symlink() or not p.is_file() or not p.stat().st_size for p in selected):
        raise ValueError('expected exact nonempty native factory/sysupgrade images')
    data = json.loads((directory / 'profiles.json').read_text())
    if data['target'] != contract['target'] or set(data['profiles']) != boards:
        raise ValueError('unexpected target/profiles')
    if not re.fullmatch(r'r[0-9]+-[0-9a-f]+', data['version_code']):
        raise ValueError('unexpected version_code')
    for board, profile in data['profiles'].items():
        images = profile.get('images', [])
        expected = {name: 'factory' if '-factory.' in name else 'sysupgrade'
                    for name in names if '-' + board + '-' in name}
        if len(images) != len(expected) or {entry.get('name') for entry in images} != set(expected):
            raise ValueError('unexpected image metadata: ' + board)
        for entry in images:
            if (entry.get('type') != expected[entry['name']]
                    or entry.get('filesystem') != 'squashfs'
                    or entry.get('size') != (directory / entry['name']).stat().st_size):
                raise ValueError('image metadata differs from output: ' + entry['name'])
    # Reject all metadata/input failures before creating either group's output.
    output.mkdir()
    for key, item in groups.items():
        destination = output if group is not None else output / key
        if destination != output:
            destination.mkdir()
        for name in item['images']:
            shutil.copyfile(directory / name, destination / name)
        validate_images(destination, item['images'])


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5) or sys.argv[1] != 'stage':
        raise SystemExit('usage: release_images.py stage TARGETS OUTPUT [GROUP]')
    stage(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4] if len(sys.argv) == 5 else None)
