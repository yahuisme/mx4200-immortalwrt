#!/usr/bin/env python3
"""Read-only admission for sequential Linux actions/cache saves.

measure streams a GNU PAX tar through native zstd (-T0 --long=30), counting
compressed bytes without retaining an archive. This duplicates save compression
and I/O; keep the trees quiescent between measurement and save. Paths, keys and
native actions/cache compression/identity must remain unchanged in the workflow.
Hostpkg is already compressed: stat its archive instead; admission's reserve
covers the native outer tar/zstd wrapper. No remote writes or deletions occur.

Use measure -> admit -> conditional save -> verify before the next admission.
Gate subsequent saves on verified=true (save actions can only warn on failure).
Fresh inventory is not an atomic reservation: serialize participating writers;
external writers and API visibility delays cannot be guaranteed by this helper.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

BUDGET = 10_000_000_000
MIN_RESERVE = 16 * 1024 * 1024
TOOLS = ('staging_dir/host', 'staging_dir/toolchain-*',
         'build_dir/host', 'build_dir/toolchain-*')


class InventoryUnavailable(Exception):
    """A read failed or returned incomplete/unusable inventory."""


def positive(value):
    number = int(value)
    if number <= 0:
        raise ValueError('bytes and budget must be positive')
    return number


def validate_target(repo, key, ref):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('repo must be OWNER/REPO')
    if not key or len(key) > 512 or any(c in key for c in '\r\n\x00,'):
        raise ValueError('invalid exact cache key')
    if not ref.startswith('refs/') or any(c.isspace() or ord(c) < 32 for c in ref):
        raise ValueError('ref must be the full current GitHub ref')


def native_paths(root, tier):
    root = Path(root).absolute()
    if not root.is_dir():
        raise ValueError(f'build root is not a directory: {root}')
    patterns = TOOLS if tier == 'tools' else ({'dl': ('dl',), 'ccache': ('.ccache',)}[tier])
    paths = []
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if not matches or any(not p.is_dir() or p.is_symlink() for p in matches):
            raise ValueError(f'missing or invalid native cache directories: {pattern}')
        paths.extend(matches)
    if any('\n' in str(p) or '\r' in str(p) for p in paths):
        raise ValueError('newline in cache path')
    return paths


def measure(root, tier):
    if tier == 'hostpkg':
        archive = Path(root) / 'hostpkg.tar.zst'
        if not archive.is_file() or archive.is_symlink():
            raise ValueError(f'missing regular hostpkg archive: {archive}')
        return positive(archive.stat().st_size)
    paths = native_paths(root, tier)
    # NUL-delimited manifest prevents option interpretation; no tree mutation.
    with tempfile.TemporaryFile() as manifest, tempfile.TemporaryFile() as tar_err, tempfile.TemporaryFile() as zstd_err:
        manifest.write(b''.join(os.fsencode(p) + b'\0' for p in paths))
        manifest.seek(0)
        tar = subprocess.Popen(['tar', '--posix', '-P', '-cf', '-', '--null',
                                '--verbatim-files-from', '-T', '-'],
                               stdin=manifest, stdout=subprocess.PIPE, stderr=tar_err)
        try:
            compressor = subprocess.Popen(['zstd', '-T0', '--long=30', '-c'],
                                          stdin=tar.stdout, stdout=subprocess.PIPE, stderr=zstd_err)
            tar.stdout.close()
            try:
                size = 0
                while chunk := compressor.stdout.read(1024 * 1024):
                    size += len(chunk)
                compressor.stdout.close()
                zstd_status = compressor.wait()
                tar_status = tar.wait()
            finally:
                if compressor.poll() is None:
                    compressor.kill()
                    compressor.wait()
            if tar_status or zstd_status:
                tar_err.seek(0)
                zstd_err.seek(0)
                raise RuntimeError('archive measurement failed: ' +
                                   (tar_err.read() + zstd_err.read()).decode(errors='replace'))
            return positive(size)
        finally:
            if tar.stdout:
                tar.stdout.close()
            if tar.poll() is None:
                tar.kill()
                tar.wait()


def inventory(repo):
    """Enumerate every ref/prefix, rejecting pagination drift instead of undercounting."""
    entries = []
    seen = set()
    total = None
    page = 1
    try:
        while True:
            response = subprocess.run(
                ['gh', 'api', '--method', 'GET',
                 f'repos/{repo}/actions/caches?per_page=100&page={page}'],
                check=True, capture_output=True, text=True, timeout=60)
            data = json.loads(response.stdout)
            count = data['total_count']
            batch = data['actions_caches']
            if type(count) is not int or count < 0 or not isinstance(batch, list):
                raise ValueError('invalid inventory schema')
            if total is None:
                total = count
            if count != total or len(batch) > 100:
                raise ValueError('inventory changed during pagination')
            for entry in batch:
                ident = entry['id']
                size = entry['size_in_bytes']
                if (type(ident) is not int or ident <= 0 or ident in seen or
                        type(size) is not int or size < 0 or
                        not isinstance(entry['key'], str) or not isinstance(entry['ref'], str)):
                    raise ValueError('invalid or duplicate inventory entry')
                seen.add(ident)
                entries.append(entry)
            if len(entries) == total:
                return entries
            if len(entries) > total or len(batch) != 100:
                raise ValueError('incomplete inventory')
            page += 1
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise InventoryUnavailable(f'inventory unavailable ({type(exc).__name__})') from exc


def admit(repo, key, ref, candidate_bytes, budget=BUDGET):
    validate_target(repo, key, ref)
    candidate_bytes, budget = positive(candidate_bytes), positive(budget)
    if budget > BUDGET:
        raise ValueError('budget cannot exceed the conservative free allowance')
    reserve = max(MIN_RESERVE, (candidate_bytes + 99) // 100)
    result = {'allowed': False, 'candidate_bytes': candidate_bytes,
              'reserve_bytes': reserve, 'budget_bytes': budget}
    try:
        entries = inventory(repo)
    except InventoryUnavailable as exc:
        return {**result, 'reason': str(exc)}
    used = sum(e['size_in_bytes'] for e in entries)
    required = used + candidate_bytes + reserve
    reason = 'fits' if required <= budget else 'insufficient headroom'
    if any(e['key'] == key and e['ref'] == ref for e in entries):
        reason = 'exact key/current ref already exists; do not overwrite'
    return {**result, 'allowed': reason == 'fits', 'reason': reason,
            'used_bytes': used, 'required_bytes': required}


def verify(repo, key, ref):
    validate_target(repo, key, ref)
    try:
        entries = inventory(repo)
    except InventoryUnavailable as exc:
        return {'verified': False, 'reason': str(exc)}
    matches = [e for e in entries if e['key'] == key and e['ref'] == ref and e['size_in_bytes'] > 0]
    return {'verified': bool(matches),
            'reason': 'exact nonempty key/current ref found' if matches else 'save not confirmed; stop subsequent saves'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    measurement = sub.add_parser('measure')
    measurement.add_argument('tier', choices=('dl', 'ccache', 'tools', 'hostpkg'))
    measurement.add_argument('root')
    for name in ('admit', 'verify'):
        command = sub.add_parser(name)
        command.add_argument('--repo', required=True)
        command.add_argument('--key', required=True)
        command.add_argument('--ref', required=True)
        if name == 'admit':
            command.add_argument('--bytes', dest='candidate_bytes', type=positive, required=True)
            command.add_argument('--budget', type=positive, default=BUDGET)
    args = vars(parser.parse_args())
    command = args.pop('command')
    if command == 'measure':
        result = {'candidate_bytes': measure(**args)}
    else:
        result = (admit if command == 'admit' else verify)(**args)
    print(json.dumps(result, sort_keys=True))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a', encoding='utf-8') as stream:
            for key, value in result.items():
                stream.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')


if __name__ == '__main__':
    main()
