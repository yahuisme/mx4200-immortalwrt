#!/usr/bin/env python3
"""Add only the verified official-default HomeWRK RAM image to native outputs."""
import json
from pathlib import Path
import shutil
import sys

NAME = 'immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb'


def stage(source, destination):
    source, destination = Path(source), Path(destination)
    data = json.loads((source / 'profiles.json').read_text())
    target = json.loads((destination / 'profiles.json').read_text())
    if (data['target'] != target['target'] or data['version_code'] != target['version_code']
            or set(data['profiles']) != {'linksys_homewrk'}):
        raise ValueError('RAM image source target/revision/profile differs')
    entries = [row for row in data['profiles']['linksys_homewrk']['images'] if row.get('name') == NAME]
    image = source / NAME
    if (len(entries) != 1 or entries[0].get('type') != 'kernel'
            or entries[0].get('filesystem') != 'initramfs'
            or image.is_symlink() or not image.is_file() or not image.stat().st_size
            or image.stat().st_size != entries[0].get('size')):
        raise ValueError('Invalid standalone HomeWRK RAM image metadata')
    images = target['profiles']['linksys_homewrk']['images']
    if (any(row.get('name') == NAME for row in images)
            or (destination / NAME).exists() or (destination / NAME).is_symlink()):
        raise ValueError('Main build must not already supply a customized RAM image')
    shutil.copyfile(image, destination / NAME)
    images.append(entries[0])
    (destination / 'profiles.json').write_text(json.dumps(target, indent=2) + '\n')


if __name__ == '__main__':
    stage(*sys.argv[1:])
