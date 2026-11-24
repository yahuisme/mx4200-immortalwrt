#!/usr/bin/env python3
"""Bind the independently built HomeWRK FIT to the formal image metadata."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

try:
    from .check_initramfs import HOMEWRK_CONFIG
except ImportError:
    from check_initramfs import HOMEWRK_CONFIG

NAME = 'immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb'
TARGET = 'qualcommax/ipq807x'
BOARD = 'linksys_homewrk'


def read(path):
    return json.loads(path.read_text())


def verify(directory, record, images=None):
    directory, record = Path(directory), Path(record)
    image = (Path(images) if images is not None else directory) / NAME
    data = read(directory / 'profiles.json')
    proof = read(record / 'initramfs.json')
    ram = read(record / 'ramboot.json')
    revision = (record / 'source-revision.txt').read_text().strip()
    sha = (record / 'source-sha.txt').read_text().strip()
    if (data['version_number'] != 'SNAPSHOT' or data['target'] != TARGET
            or data['version_code'] != revision or not re.fullmatch(r'r[1-9][0-9]*-[0-9a-f]+', revision)
            or not re.fullmatch(r'[0-9a-f]{40}', sha)
            or ram.get('source_sha') != sha or proof.get('source_sha') != sha
            or ram.get('revision') != revision or proof.get('revision') != revision
            or ram.get('pristine') is not True or ram.get('customization') != 'Chinese LuCI only'
            or proof.get('name') != NAME or proof.get('language') != 'zh_cn'
            or proof.get('complete_cpio') is not True or proof.get('fit_config') != HOMEWRK_CONFIG):
        raise ValueError('Invalid HomeWRK RAM build/inspection identity')
    if hashlib.sha256((record / 'ramboot.config').read_bytes()).hexdigest() != ram.get('config_sha256'):
        raise ValueError('HomeWRK RAM config differs from recorded configuration')
    entries = [row for row in data['profiles'][BOARD]['images'] if row.get('name') == NAME]
    if (len(entries) != 1 or entries[0].get('type') != 'kernel'
            or entries[0].get('filesystem') != 'initramfs'
            or image.is_symlink() or not image.is_file() or type(proof.get('size')) is not int
            or type(entries[0].get('size')) is not int
            or not 0 < image.stat().st_size == proof['size'] == entries[0]['size']):
        raise ValueError('Invalid HomeWRK RAM FIT size/type')
    with image.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != entries[0].get('sha256') or digest != proof.get('sha256'):
        raise ValueError('HomeWRK RAM FIT SHA-256 mismatch')
    return entries[0]


def merge(source, destination, record):
    source, destination = Path(source), Path(destination)
    entry = verify(source, record)
    ram = read(source / 'profiles.json')
    path = destination / 'profiles.json'
    main = read(path)
    if (set(ram['profiles']) != {BOARD} or ram['target'] != main['target']
            or ram['version_number'] != main['version_number'] or ram['version_code'] != main['version_code']):
        raise ValueError('RAM image source target/revision/profile differs')
    images = main['profiles'][BOARD]['images']
    if (any(row.get('filesystem') == 'initramfs' for profile in main['profiles'].values() for row in profile['images'])
            or (destination / NAME).exists() or (destination / NAME).is_symlink()):
        raise ValueError('Formal build must not already supply an initramfs')
    shutil.copyfile(source / NAME, destination / NAME)
    images.append(entry)
    path.write_text(json.dumps(main, indent=2) + '\n')


if __name__ == '__main__':
    if sys.argv[1:2] == ['merge'] and len(sys.argv) == 5:
        merge(*sys.argv[2:])
    elif sys.argv[1:2] == ['verify'] and len(sys.argv) == 4:
        verify(*sys.argv[2:])
    else:
        raise SystemExit('usage: stage_ramboot.py merge SOURCE DESTINATION RECORD | verify DIRECTORY RECORD')
