#!/usr/bin/env python3
"""Small, cold-schema MX4200 cache helper (Python stdlib + GNU tar + gh).

Run prepare AFTER final defconfig and BEFORE any tools build/restore. Keep the
same absolute build root and host environment. Exact tc-key only; rolling-prefix
is the ONLY restore-prefix. No legacy paths, migration, or hostpkg cache.
pack creates one PAX/gzip archive and reports its actual size. Save THAT file,
not the original trees. actions/cache adds its own transport wrapper; admission
reserves overhead, but cannot disable the action's outer compression.

Writers MUST be serialized (workflow concurrency, no competing cache writers).
For each tier: pack -> admit -> save archive -> prune. An admission denial must
skip saving and pruning, not remove old caches. API failures fail closed. This
is a conservative coexistence gate, not a quota reservation against other jobs.
All commands print JSON; --output additionally appends scalar GitHub outputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

# Bump whenever prepare/inputs fingerprint or timestamp rules change: old
# toolchains must never be accepted under a new interpretation of their inputs.
SCHEMA = 'mx4200-pax-v2'
EPOCH_NS = 1600000000000000000
LIMIT = 10_000_000_000  # conservative decimal 10 GB, includes ALL refs/namespaces
ROOTS = ('tools', 'toolchain', 'include', 'target', 'scripts')


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd)


def scope(ref):
    if not ref.startswith('refs/') or '\n' in ref:
        raise ValueError('a complete GitHub ref is required')
    return f'{SCHEMA}-{hashlib.sha256(ref.encode()).hexdigest()[:16]}-'


def inputs(root):
    """Tracked source plus nonignored additions; no generated config frontend.

    Full target/shared input trees and final config are deliberately conservative.
    Unsupported links fail closed rather than silently omitting their targets.
    """
    names = run('git', 'ls-files', '-z', '--cached', '--others',
                '--exclude-standard', '--', *ROOTS, 'Makefile', 'rules.mk',
                'Config.in', 'config', cwd=root).decode().split('\0')
    names = sorted(set(n for n in names if n))
    if not names or not (root / '.config').is_file():
        raise ValueError('prepared git source and final .config required')
    names.append('.config')
    selected = set(names)
    for name in names:
        p = root / name
        if p.is_symlink():
            dest = p.resolve(strict=True)
            if not dest.is_relative_to(root) or str(dest.relative_to(root)) not in selected or not dest.is_file():
                raise ValueError(f'unsupported source symlink: {name}')
        elif not p.is_file():
            raise ValueError(f'missing/non-file source input: {name}')
    return names


def prepare(root, ref, host_id):
    root = root.resolve()
    names = inputs(root)
    h = hashlib.sha256()
    # Absolute recipe paths occur in upstream find_md5; host binaries are not portable.
    host = [platform.system(), platform.machine(), host_id,
            run('gcc', '--version').decode(), run('g++', '--version').decode(),
            run('ld', '--version').decode(), run('make', '--version').decode(),
            run('dpkg-query', '-W', '-f=${Package}=${Version}\n').decode()]
    h.update(json.dumps([SCHEMA, str(root), host], sort_keys=True).encode())
    for name in names:
        p = root / name
        h.update(json.dumps([name, p.lstat().st_mode & 0o7777,
                             os.readlink(p) if p.is_symlink() else None]).encode())
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                h.update(block)
        h.update(b'\0')
    # Only enumerated source files: never stamps/build_dir/staging/tmp metadata.
    # A fixed old time makes freshly checked-out recipes match upstream find_md5.
    for name in names:
        os.utime(root / name, ns=(EPOCH_NS, EPOCH_NS), follow_symlinks=False)
    prefix = scope(ref)
    return {'tc-key': prefix + 'tc-' + h.hexdigest(),
            'rolling-prefix': prefix + 'rolling-', 'source-files': len(names)}


def paths(root, tier):
    if tier == 'rolling':
        result = ['dl', '.ccache']
    else:
        result = ['build_dir/host', 'staging_dir/host']
        build = sorted(p.name for p in (root / 'build_dir').glob('toolchain-*'))
        stage = sorted(p.name for p in (root / 'staging_dir').glob('toolchain-*'))
        if not build or build != stage:
            raise ValueError('matching build_dir/staging_dir toolchain directories required')
        result += [f'{base}/{name}' for base in ('build_dir', 'staging_dir') for name in build]
    for name in result:
        p = root / name
        if not p.is_dir() or p.is_symlink():
            raise ValueError(f'missing/linked cache tree: {name}')
    return result


def allowed(name, tier):
    parts = PurePosixPath(name).parts
    if not parts or name.startswith('/') or '..' in parts:
        return False
    if tier == 'rolling':
        return parts[0] in ('dl', '.ccache')
    return (len(parts) >= 2 and parts[0] in ('build_dir', 'staging_dir')
            and (parts[1] == 'host' or parts[1].startswith('toolchain-')))


def pack(root, tier, archive):
    root, archive = root.resolve(), archive.resolve()
    if archive.is_relative_to(root):
        raise ValueError('archive must be outside build root')
    names = paths(root, tier)
    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = archive.with_name(archive.name + '.partial')
    try:
        compressor = 'pigz -1' if shutil.which('pigz') else 'gzip -1'
        subprocess.run(['tar', '--format=pax', '-I', compressor, '-cf', str(partial),
                        '-C', str(root), '--', *names], check=True)
        partial.replace(archive)
    finally:
        partial.unlink(missing_ok=True)
    return {'archive': str(archive), 'bytes': archive.stat().st_size}


def unpack(root, tier, archive):
    root = root.resolve()
    # Validate the full member list before any extraction; GNU tar retains ns.
    # Absolute compiler symlinks are legitimate, but no member may traverse a link.
    with tarfile.open(archive, 'r:gz') as tf:
        members = tf.getmembers()
        links = {m.name.rstrip('/') for m in members if m.issym()}
        seen = set()
        for m in members:
            name = m.name.rstrip('/')
            if not allowed(name, tier) or name in seen:
                raise ValueError(f'unsafe/duplicate archive member: {name}')
            seen.add(name)
            if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):
                raise ValueError('special archive member forbidden')
            parents = PurePosixPath(name).parents
            if any(str(p) in links or (root / str(p)).is_symlink() for p in parents):
                raise ValueError('archive member traverses symlink')
            if m.islnk() and (not allowed(m.linkname, tier) or m.linkname in links):
                raise ValueError('unsafe hardlink')
        targets = sorted({str(PurePosixPath(m.name).parts[0]) if tier == 'rolling'
                          else '/'.join(PurePosixPath(m.name).parts[:2]) for m in members})
        directories = {m.name.rstrip('/') for m in members if m.isdir()}
        if not targets or not set(targets) <= directories:
            raise ValueError('cache roots must be explicit directories')
        if tier == 'rolling':
            complete = targets == ['.ccache', 'dl']
        else:
            build = {n.split('/')[1] for n in targets if n.startswith('build_dir/')}
            stage = {n.split('/')[1] for n in targets if n.startswith('staging_dir/')}
            complete = build == stage and 'host' in build and len(build) > 1
        if not complete:
            raise ValueError('incomplete paired cache roots')
    # Only selected roots move; hostpkg and target outputs never participate.
    # A root-local backup guarantees same-filesystem atomic renames per tree.
    backup = Path(tempfile.mkdtemp(prefix='.cache-backup-', dir=root))
    moved = []
    extracting = False
    try:
        for name in targets:
            source = root / name
            if source.exists() or source.is_symlink():
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                source.rename(saved)
                moved.append(name)
        extracting = True
        subprocess.run(['tar', '-xzf', str(Path(archive).resolve()), '--no-same-owner',
                        '-C', str(root)], check=True)
        paths(root, tier)
    except BaseException:
        if extracting:
            for name in targets:
                p = root / name
                if p.is_symlink() or (p.exists() and not p.is_dir()):
                    p.unlink()
                elif p.exists():
                    shutil.rmtree(p)
        for name in reversed(moved):
            (backup / name).rename(root / name)
        shutil.rmtree(backup)
        raise
    # If rollback itself fails, keep the backup for manual recovery.
    shutil.rmtree(backup)
    return {'restored': True}


def inventory(repo):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('invalid repository')
    pages = json.loads(run('gh', 'api', '--paginate', '--slurp',
                          f'repos/{repo}/actions/caches?per_page=100'))
    rows = [r for page in pages for r in page['actions_caches']]
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('unstable duplicate cache inventory')
    for r in rows:
        if not isinstance(r['size_in_bytes'], int) or r['size_in_bytes'] < 0:
            raise ValueError('invalid inventory size')
    return rows


def owned_prefix(key, ref):
    prefix = scope(ref)
    for tier in ('tc-', 'rolling-'):
        if key.startswith(prefix + tier) and len(key) > len(prefix + tier):
            return prefix + tier
    raise ValueError('key outside current schema/ref namespace')


def admission(rows, size, key, ref):
    owned_prefix(key, ref)
    if size <= 0:
        raise ValueError('nonempty archive required')
    used = sum(r['size_in_bytes'] for r in rows)
    overhead = max(64 * 1024 * 1024, size // 100)
    exists = any(r['key'] == key and r['ref'] == ref for r in rows)
    return {'admitted': not exists and used + size + overhead <= LIMIT,
            'used': used, 'bytes': size, 'overhead': overhead, 'limit': LIMIT}


def prune(repo, ref, key, delete=False):
    prefix = owned_prefix(key, ref)
    # A successful save may briefly be absent or report zero bytes in the API.
    # Retry only confirmation, never API errors or any deletion/readback.
    attempt = 0
    while True:
        rows = inventory(repo)
        matches = [r for r in rows if r['key'] == key and r['ref'] == ref
                   and r['size_in_bytes'] > 0]
        if matches or attempt == 2:
            break
        attempt += 1
        time.sleep(2)
    if len(matches) != 1:
        raise ValueError('exact nonempty replacement not uniquely confirmed; no deletion')
    replacement = matches[0]
    victims = [r['id'] for r in rows if r['ref'] == ref
               and r['key'].startswith(prefix) and r['key'] != key
               and r['created_at'] <= replacement['created_at']]
    if not delete:
        return {'confirmed': True, 'delete-ids': victims, 'deleted': []}
    for cache_id in victims:
        subprocess.run(['gh', 'api', '--method', 'DELETE',
                        f'repos/{repo}/actions/caches/{cache_id}'], check=True)
    after = inventory(repo)
    if (any(r['id'] in victims for r in after)
            or not any(r['id'] == replacement['id'] and r['size_in_bytes'] > 0 for r in after)):
        raise ValueError('post-delete readback failed; cleanup may be partial')
    return {'confirmed': True, 'deleted': victims,
            'used': sum(r['size_in_bytes'] for r in after)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', help='append scalar fields to GITHUB_OUTPUT')
    sub = p.add_subparsers(dest='cmd', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--root', type=Path, required=True)
    prep.add_argument('--ref', required=True)
    prep.add_argument('--host-id', required=True, help='runner image version + build environment policy')
    for command in ('pack', 'unpack'):
        c = sub.add_parser(command)
        c.add_argument('--root', type=Path, required=True)
        c.add_argument('--tier', choices=['tc', 'rolling'], required=True)
        c.add_argument('--archive', type=Path, required=True)
    for command in ('admit', 'prune'):
        c = sub.add_parser(command)
        c.add_argument('--repo', required=True)
        c.add_argument('--ref', required=True)
        c.add_argument('--key', required=True)
        if command == 'admit':
            c.add_argument('--archive', type=Path, required=True)
        else:
            c.add_argument('--delete', action='store_true', help='actually delete confirmed superseded entries')
    args = p.parse_args()
    if args.cmd == 'prepare':
        result = prepare(args.root, args.ref, args.host_id)
    elif args.cmd in ('pack', 'unpack'):
        result = globals()[args.cmd](args.root, args.tier, args.archive)
    elif args.cmd == 'admit':
        result = admission(inventory(args.repo), args.archive.stat().st_size, args.key, args.ref)
    else:
        result = prune(args.repo, args.ref, args.key, args.delete)
    print(json.dumps(result, sort_keys=True))
    if args.output:
        with open(args.output, 'a') as f:
            for key, value in result.items():
                if isinstance(value, (str, int, bool)):
                    f.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')


if __name__ == '__main__':
    main()
