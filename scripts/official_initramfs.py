#!/usr/bin/env python3
"""Resolve official stable HomeWRK initramfs metadata; never use snapshot builds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from html.parser import HTMLParser
import re
import time
import http.client
import urllib.error
from typing import Callable, TypeVar
import urllib.request

RELEASES = 'https://downloads.immortalwrt.org/releases/'
TARGET = 'qualcommax/ipq807x'
NAME = 'immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb'
GROUP = 'mx4300-homewrk'
VERSION = r'[0-9]+\.[0-9]+\.[0-9]+'
SHA256 = r'[0-9a-f]{64}'
MAX_IMAGE_SIZE = 128 * 1024 * 1024


class ReleaseIndex(HTMLParser):
    def __init__(self):
        super().__init__()
        self.versions = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for key, value in attrs:
                if key == 'href' and value and re.fullmatch(VERSION + '/', value):
                    self.versions.add(value[:-1])


Result = TypeVar('Result')


def _retry(operation: Callable[[], Result]) -> Result:
    for attempt in range(3):
        try:
            return operation()
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.IncompleteRead, http.client.RemoteDisconnected) as error:
            if (attempt == 2 or (isinstance(error, urllib.error.HTTPError)
                    and error.code not in (408, 429, 500, 502, 503, 504))):
                raise
            time.sleep(2 ** attempt)
    raise AssertionError('Unreachable retry state')


def _metadata(url):
    def fetch():
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('Official metadata exceeds size limit')
        return data.decode('utf-8')
    return _retry(fetch)


def resolve():
    """Resolve once per build; fail if the latest release lacks this exact image."""
    index = ReleaseIndex()
    index.feed(_metadata(RELEASES))
    if not index.versions:
        raise ValueError('No strict stable release directories found')
    version = max(index.versions, key=lambda text: tuple(map(int, text.split('.'))))
    base = f'{RELEASES}{version}/targets/{TARGET}/'
    profiles = json.loads(_metadata(base + 'profiles.json'))
    if profiles.get('target') != TARGET or profiles.get('version_number') != version:
        raise ValueError('Official profiles target/version mismatch')
    images = profiles.get('profiles', {}).get('linksys_homewrk', {}).get('images', [])
    rows = [row for row in images
            if row.get('type') == 'kernel' and row.get('filesystem') == 'initramfs']
    source_name = NAME.replace('immortalwrt-', f'immortalwrt-{version}-', 1)
    if len(rows) != 1 or rows[0].get('name') != source_name:
        raise ValueError('Latest stable lacks one exact HomeWRK initramfs kernel')
    row = rows[0]
    if (type(row.get('size')) is not int or not 0 < row['size'] <= MAX_IMAGE_SIZE
            or not isinstance(row.get('sha256'), str)
            or not re.fullmatch(SHA256, row['sha256'])):
        raise ValueError('Invalid official image size/SHA-256')
    checksums = []
    for line in _metadata(base + 'sha256sums').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', line)
        if match and match[2] == source_name:
            checksums.append(match[1])
    if checksums != [row['sha256']]:
        raise ValueError('Official profiles/sha256sums mismatch or duplicate')
    return {'version': version, 'url': base + source_name, 'source_name': source_name,
            'name': NAME, 'size': row['size'], 'sha256': row['sha256'],
            'target': TARGET, 'group': GROUP}


def _validate_record(record):
    if not isinstance(record, dict):
        raise ValueError('Invalid official initramfs record')
    version = record.get('version')
    if not isinstance(version, str) or not re.fullmatch(VERSION, version):
        raise ValueError('Invalid official stable record version')
    source = NAME.replace('immortalwrt-', f'immortalwrt-{version}-', 1)
    expected = {'name': NAME, 'source_name': source, 'target': TARGET, 'group': GROUP,
                'url': f'{RELEASES}{version}/targets/{TARGET}/{source}'}
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError('Official record identity/URL mismatch')
    if (type(record.get('size')) is not int or not 0 < record['size'] <= MAX_IMAGE_SIZE
            or not isinstance(record.get('sha256'), str)
            or not re.fullmatch(SHA256, record['sha256'])):
        raise ValueError('Invalid official record size/SHA-256')
    return record


def load_record(path):
    """Load the already-resolved build record without consulting current releases."""
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode) or not path.stat().st_size:
        raise ValueError('Official record must be a nonempty regular non-symlink file')
    return _validate_record(json.loads(path.read_text(encoding='utf-8')))


def verify(path, record):
    """Verify one original binary against the build's frozen official metadata."""
    _validate_record(record)
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Official image must be a regular non-symlink file')
    if path.stat().st_size != record['size']:
        raise ValueError('Official image size mismatch')
    digest = hashlib.sha256()
    with path.open('rb') as image:
        for chunk in iter(lambda: image.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != record['sha256']:
        raise ValueError('Official image SHA-256 mismatch')
    return record


def download(destination, record_path):
    """Stage unchanged bytes under the versionless name and atomically save proof."""
    destination, record_path = Path(destination), Path(record_path)
    image_path = destination / NAME
    if (record_path.resolve() == image_path.resolve()
            or (record_path.exists() and image_path.exists()
                and record_path.samefile(image_path))):
        raise ValueError('Official image and record paths must not alias')
    for path in (image_path, record_path):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Official output must be a regular non-symlink file')
    record = _validate_record(resolve())
    destination.mkdir(parents=True, exist_ok=True)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    image_temp = record_temp = None
    try:
        def fetch():
            assert image_temp is not None
            with image_temp.open('wb') as output:
                with urllib.request.urlopen(record['url'], timeout=30) as response:
                    length = response.headers.get('Content-Length') if hasattr(response, 'headers') else None
                    if length is not None and int(length) != record['size']:
                        raise ValueError('Official Content-Length size mismatch')
                    count = 0
                    while chunk := response.read(min(1024 * 1024, record['size'] - count + 1)):
                        count += len(chunk)
                        if count > record['size']:
                            raise ValueError('Official image exceeds expected size')
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            verify(image_temp, record)
        with tempfile.NamedTemporaryFile(dir=destination, prefix='.official-', delete=False) as output:
            image_temp = Path(output.name)
        _retry(fetch)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=record_path.parent,
                                         prefix='.official-record-', delete=False) as output:
            record_temp = Path(output.name)
            json.dump(record, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(image_temp, destination / NAME)
        os.replace(record_temp, record_path)
        return record
    finally:
        for path in (image_temp, record_temp):
            if path is not None:
                path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path,
                        help='download directory (or original binary with --verify)')
    parser.add_argument('--record', required=True, type=Path)
    parser.add_argument('--verify', action='store_true', help='offline verification only')
    args = parser.parse_args()
    try:
        result = (verify(args.destination, load_record(args.record)) if args.verify
                  else download(args.destination, args.record))
    except (OSError, ValueError) as error:
        parser.exit(1, f'official initramfs: {error}\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
