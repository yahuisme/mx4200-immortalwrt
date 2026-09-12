#!/usr/bin/env python3
"""Exact hostpkg companion cache; never broaden the existing toolchain key."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

EPOCH = 946684800
ARTIFACTS = ('build_dir/hostpkg', 'staging_dir/hostpkg')
SCHEMA = 'mx4200-hostpkg-v2'


def fingerprint(root, names, normalize=False, excluded=()):
    digest = hashlib.sha256()
    for name in names:
        base = root / name
        if not base.is_dir() or base.is_symlink():
            raise ValueError('Missing or linked input root: ' + name)
        for directory, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d != '.git'
                             and Path(directory) / d not in excluded)
            for name_ in sorted(set(dirs + files)):
                item = Path(directory) / name_
                relative = item.relative_to(root)
                if item.name == '.git' or item in excluded:
                    continue
                if item.is_symlink():
                    target = item.resolve(strict=True)
                    # Source feed links are allowed only within the hashed roots.
                    if (not any(target.is_relative_to(root / n) for n in names)
                            or any(target.is_relative_to(p) for p in excluded)):
                        raise ValueError('Uncovered linked input: ' + str(relative))
                    content = os.readlink(item).encode()
                elif item.is_file():
                    content = item.read_bytes()
                    if normalize:
                        os.utime(item, (EPOCH, EPOCH))
                elif item.is_dir():
                    continue
                else:
                    raise ValueError('Unsupported input: ' + str(relative))
                digest.update(json.dumps([str(relative), item.lstat().st_mode,
                                          hashlib.sha256(content).hexdigest()]).encode())
    return digest.hexdigest()


def cache_key(root, toolchain, bootstrap):
    # Conservative complete package/feed source inventory includes indirect
    # PKG_FILE_DEPENDS, shared language recipes and arbitrary host dependencies.
    # Do not hash generated tmp metadata or cache target build/staging products.
    # scripts/feeds update_index writes these sibling scan products. Their
    # info/.files-* and .overrides-* names contain the process SCAN_COOKIE.
    # Exclude only metadata paired with an actual feed, never nested *.tmp
    # recipe inputs or bootstrap files. Keep all prepared source content.
    excluded = set()
    for feed in (root / 'feeds').iterdir():
        if feed.is_dir() and not feed.name.endswith('.tmp'):
            excluded.update(feed.with_name(feed.name + suffix)
                            for suffix in ('.tmp', '.index', '.targetindex'))
    source = fingerprint(root, ('package', 'feeds'), normalize=True,
                         excluded=excluded)
    return hashlib.sha256(json.dumps([SCHEMA, str(root.resolve()), toolchain,
                                     bootstrap, source]).encode()).hexdigest()


def admitted(entries, candidate):
    sizes = [int(entry['size_in_bytes']) for entry in entries]
    if any(size < 0 for size in sizes):
        raise ValueError('Invalid cache inventory size')
    # Decimal 10GB is conservative versus 10GiB. Reserve outer cache tar overhead.
    return candidate > 0 and sum(sizes) + candidate + max(16_777_216, candidate // 100) <= 10_000_000_000


def main():
    command, root_, *args = sys.argv[1:]
    root = Path(root_).resolve()
    if command == 'key':
        goroot = Path(subprocess.check_output(['go', 'env', 'GOROOT'], text=True).strip()).resolve()
        bootstrap = json.dumps([str(goroot), fingerprint(goroot.parent, (goroot.name,))])
        key = cache_key(root, args[0], bootstrap)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('key=' + key + '\n')
        print('Hostpkg input: ' + key)
    elif command == 'admit':
        archive = Path(args[0])
        raw = subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
            'repos/' + os.environ['GITHUB_REPOSITORY'] + '/actions/caches?per_page=100'], text=True)
        entries = [entry for page in json.loads(raw) for entry in page['actions_caches']]
        allowed = admitted(entries, archive.stat().st_size)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('allowed=' + str(allowed).lower() + '\n')
        print(json.dumps({'inventory_bytes': sum(e['size_in_bytes'] for e in entries),
                          'candidate_bytes': archive.stat().st_size, 'allowed': allowed}))
    elif command == 'pack':
        archive = str(Path(args[0]).resolve())
        for name in ARTIFACTS:
            if not (root / name).is_dir():
                raise ValueError('Missing paired artifact: ' + name)
        subprocess.run(['tar', '--format=posix', '-I', 'zstd -T0 -3', '-cf', archive,
                        '-C', str(root), *ARTIFACTS], check=True)
        print('Hostpkg compressed bytes:', Path(archive).stat().st_size)
    elif command == 'unpack':
        archive = str(Path(args[0]).resolve())
        subprocess.run(['tar', '-I', 'zstd', '-xf', archive, '-C', str(root)], check=True)
    else:
        raise ValueError('Unknown command: ' + command)


if __name__ == '__main__':
    main()
