#!/usr/bin/env python3
"""Exact hostpkg companion key, without changing the hot toolchain key policy."""
import hashlib
import json
import os
from pathlib import Path
import sys

EPOCH_NS = 1600000000000000000
SCHEMA = 'mx4200-hostpkg-v1'


def fingerprint(root, names, normalize=False, excluded=()):
    digest = hashlib.sha256()
    sources = []
    for name in names:
        base = root / name
        if not base.is_dir() or base.is_symlink():
            raise ValueError('Missing or linked input root: ' + name)
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d != '.git' and Path(directory) / d not in excluded)
            for entry in sorted(set(dirs + files)):
                item = Path(directory) / entry
                if item.name == '.git' or item in excluded:
                    continue
                if item.is_symlink():
                    target = item.resolve(strict=True)
                    if (not any(target.is_relative_to(root / n) for n in names)
                            or any(target.is_relative_to(p) for p in excluded)
                            or '.git' in target.relative_to(root).parts):
                        raise ValueError('Uncovered source link: ' + str(item))
                    content = hashlib.sha256(os.readlink(item).encode()).hexdigest()
                elif item.is_file():
                    h = hashlib.sha256()
                    with item.open('rb') as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            h.update(block)
                    content = h.hexdigest()
                    sources.append(item)
                elif item.is_dir():
                    continue
                else:
                    raise ValueError('Unsupported source input: ' + str(item))
                digest.update(json.dumps([str(item.relative_to(root)), item.lstat().st_mode, content]).encode())
    # Only validated source inputs, never build/staging stamps or scan metadata.
    if normalize:
        for item in sources:
            os.utime(item, ns=(EPOCH_NS, EPOCH_NS))
    return digest.hexdigest()


def cache_key(root, toolchain, bootstrap):
    root, bootstrap = root.resolve(), bootstrap.resolve()
    excluded = set()
    for feed in (root / 'feeds').iterdir():
        if feed.is_dir() and not feed.is_symlink() and not feed.name.endswith('.tmp'):
            excluded.update(feed.with_name(feed.name + suffix)
                            for suffix in ('.tmp', '.index', '.targetindex'))
    source = fingerprint(root, ('package', 'feeds'), normalize=True, excluded=excluded)
    go = fingerprint(bootstrap.parent, (bootstrap.name,))
    return hashlib.sha256(json.dumps([SCHEMA, str(root), toolchain, str(bootstrap), go, source]).encode()).hexdigest()


def main():
    root, toolchain, bootstrap = sys.argv[1:]
    key = toolchain.split('-tc-', 1)[0] + '-hostpkg-' + cache_key(Path(root), toolchain, Path(bootstrap))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('hostpkg-key=' + key + '\n')
    print(json.dumps({'hostpkg-key': key}))


if __name__ == '__main__':
    main()
