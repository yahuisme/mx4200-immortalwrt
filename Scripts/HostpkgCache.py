#!/usr/bin/env python3
"""Exact hostpkg companion key, without changing the hot toolchain key policy."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

EPOCH_NS = 1600000000000000000
SCHEMA = 'mx4200-hostpkg-v2'
# yahuisme/packages@6ff620f4df18eed4321be0778dac03f25909f6ad
# immortalwrt/luci@830486a7e412a83f233e9c18bd1eb3668212c799
# Fixtures retain the audited bytes. No host recipe: luci.mk only copies,
# minifies and translates this payload for target installation. src/patches
# and any future top-level inputs must fall back to the complete inventory.
HOMEPROXY_RECIPE = 'f409a76551babc4cfdef2b191c74f074d37866545c6eb17681989e1d2cf1d1f2'
LUCI_MK = '15d8403c377883f37bc2d87e46c3d41790ba05fab743d14d648a3d7a12327efa'


def homeproxy_contract(root):
    package = root / 'package/luci-app-homeproxy'
    recipe = package / 'Makefile'
    luci = root / 'feeds/luci/luci.mk'
    runtime = {package / name for name in ('htdocs', 'root', 'po')}
    files = {'Makefile', 'LICENSE', 'UPSTREAM-TRACKING.md'}
    directories = {'htdocs', 'root', 'po', 'tests'}
    if (not package.is_dir() or package.is_symlink()
            or (root / 'feeds/luci').is_symlink()
            or not recipe.is_file() or recipe.is_symlink()
            or not luci.is_file() or luci.is_symlink()):
        return set(), {}
    for item in package.iterdir():
        if item.is_symlink() or not ((item.name in files and item.is_file())
                                    or (item.name in directories and item.is_dir())):
            return set(), {}
    data = re.sub(rb'(?m)^(PKG_VERSION|PKG_RELEASE):=[0-9]+$',
                  rb'\1:=@metadata@', recipe.read_bytes())
    if (hashlib.sha256(data).hexdigest() != HOMEPROXY_RECIPE
            or hashlib.sha256(luci.read_bytes()).hexdigest() != LUCI_MK):
        return set(), {}
    # Do not hide links, even within excluded payload directories.
    for path in runtime:
        for directory, dirs, names in os.walk(path, followlinks=False):
            for name in dirs + names:
                item = Path(directory) / name
                if item.is_symlink():
                    raise ValueError('Linked HomeProxy payload: ' + str(item))
    return runtime, {recipe: data}


def fingerprint(root, names, normalize=False, excluded=(), replacements=None):
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
                            or any(target.is_relative_to(p) or p.is_relative_to(target)
                                   for p in excluded)
                            or (replacements and target in replacements)
                            or '.git' in target.relative_to(root).parts):
                        raise ValueError('Uncovered source link: ' + str(item))
                    content = hashlib.sha256(os.readlink(item).encode()).hexdigest()
                elif item.is_file():
                    h = hashlib.sha256()
                    if replacements and item in replacements:
                        h.update(replacements[item])
                    else:
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
    runtime, replacements = homeproxy_contract(root)
    excluded.update(runtime)
    source = fingerprint(root, ('package', 'feeds'), normalize=True,
                         excluded=excluded, replacements=replacements)
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
