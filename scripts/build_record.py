#!/usr/bin/env python3
"""Collect local build inputs/outputs; retain partial evidence on failure."""
import json
import os
import re
try:
    from .release_images import images
except ImportError:
    from release_images import images
from pathlib import Path
import shutil
import subprocess
import sys


def collect(source, destination):
    # The collector runs as root in Docker; artifacts must be runner-readable.
    os.umask(0o022)
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    errors, revisions = [], []

    def revision(label, path):
        try:
            sha = subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--verify', 'HEAD'], text=True).strip()
            url = subprocess.check_output(['git', '-C', str(path), 'remote', 'get-url', 'origin'], text=True).strip()
            if not re.fullmatch(r'[0-9a-f]{40}', sha):
                raise ValueError('malformed Git SHA: ' + label)
            revisions.append(dict(name=label, url=url, sha=sha))
        except (OSError, ValueError, subprocess.CalledProcessError):
            errors.append('Git revision unavailable: ' + label)

    def copy(path, name):
        try:
            if path.is_file() and path.stat().st_size:
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            else:
                errors.append('Missing or empty: ' + str(path))
        except OSError as exc:
            errors.append(f'Copy failed: {path}: {exc}')

    try:
        inventory = subprocess.check_output(
            ['dpkg-query', '-W', '-f=${Package}\t${Architecture}\t${Version}\n'], text=True)
        if not inventory.strip():
            errors.append('Empty container package inventory')
        (destination / 'dpkg-packages.tsv').write_text(
            '\n'.join(sorted(inventory.splitlines())) + '\n')
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f'Container package inventory failed: {exc}')

    revision('source', source)
    feeds = sorted(p for p in (source / 'feeds').glob('*') if (p / '.git').exists())
    if not feeds:
        errors.append('No Git feed revisions')
    for feed in feeds:
        revision('feed/' + feed.name, feed)
    # Compare the preparation log against actual Git checkouts, not remote HEAD.
    copy(source / 'source-revisions.txt', 'source-revisions.txt')
    try:
        rows = [line.split() for line in (source / 'source-revisions.txt').read_text().splitlines()]
        actual = {r['name'].replace('feed/', 'feeds/'): r['sha'] for r in revisions}
        if (any(len(row) != 2 for row in rows) or len(rows) != len(actual)
                or dict(rows) != actual):
            errors.append('Source revision log differs from actual source/feeds')
    except (OSError, ValueError):
        errors.append('Source revision log unavailable or malformed')
    copy(source / '.config', 'final.config')
    copy(source / '.custom-revisions.tsv', 'custom-revisions.tsv')
    for name in ('feeds.conf', 'feeds.conf.default'):
        if (source / name).is_file():
            copy(source / name, name)
    custom = source / '.custom-revisions.tsv'
    if custom.is_file():
        rows = [line.split('\t') for line in custom.read_text().splitlines()]
        expected = {'yahuisme/packages', 'luci-theme-aurora', 'luci-app-aurora-config'}
        if (len(rows) != len(expected)
                or any(len(row) != 3 for row in rows)
                or {row[0] for row in rows if row} != expected
                or any(not row[1] or not re.fullmatch(r'[0-9a-f]{40}', row[2])
                       for row in rows if len(row) == 3)):
            errors.append('Incomplete custom package revisions')
    if custom.is_file() and not any(e == 'Incomplete custom package revisions' for e in errors):
        revisions.extend(dict(name='custom/' + row[0], url=row[1], sha=row[2]) for row in rows)
    (destination / 'revisions.json').write_text(json.dumps(revisions, indent=2) + '\n')
    targets = source / 'bin/targets'
    manifests = sorted(targets.glob('**/*.manifest'))
    if not manifests:
        errors.append('No package manifest')
    for path in manifests + sorted(targets.glob('**/profiles.json')):
        relative = path.relative_to(targets)
        target = destination / 'targets' / relative
        copy(path, str(target.relative_to(destination)))
    checksums = []
    try:
        entries = images(targets / 'qualcommax/ipq807x')
        (destination / 'images.json').write_text(json.dumps(entries, indent=2) + '\n')
        checksums = [f"{entry['digest'].removeprefix('sha256:')}  qualcommax/ipq807x/{entry['name']}\n" for entry in entries]
    except (OSError, ValueError) as exc:
        errors.append('MX4200 images invalid: ' + str(exc))
    (destination / 'sha256sums').write_text(''.join(checksums))
    (destination / 'diagnostics.json').write_text(json.dumps({'errors': errors}, indent=2) + '\n')
    # Normalize modes even when the collector inherited a restrictive root umask.
    for path in [destination, *destination.rglob('*')]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)
    if errors:
        raise SystemExit('; '.join(errors))


if __name__ == '__main__':
    collect(*sys.argv[1:])
