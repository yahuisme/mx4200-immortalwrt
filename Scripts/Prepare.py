#!/usr/bin/env python3
"""Resolve stable sources and transplant only the reviewed NSS delta. No build."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = 'https://github.com/immortalwrt/immortalwrt.git'
DONOR = 'https://github.com/LiBwrt/LibWrt.git'
VERSIONS = 'https://downloads.immortalwrt.org/.versions.json'


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def get_json(url):
    headers = {'User-Agent': 'mx4200-source-preparation'}
    if url.startswith('https://api.github.com/') and os.getenv('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return json.load(response)


def stable_tag(value):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', value):
        raise ValueError('Not a stable version tag: ' + value)
    return value


def resolve():
    version = get_json(VERSIONS)['stable_version']
    release = get_json('https://api.github.com/repos/LiBwrt/LibWrt/releases/latest')
    official = stable_tag('v' + version)
    donor = stable_tag(release['tag_name'])
    if release['draft'] or release['prerelease'] or official != donor:
        raise ValueError(f'Unsupported release pair: official={official}, NSS={donor}')
    return {'official_tag': official, 'donor_tag': donor,
            'official_version_source': VERSIONS, 'donor_release_url': release['html_url'],
            'donor_published_at': release['published_at']}


def tracked(tree):
    return set(run('git', 'ls-files', cwd=tree).splitlines())


def file_delta(official, donor, name):
    """Hash only the reviewed edit, including file type/mode and deletions.

    Shared upstream context can evolve in both releases without pinning commits.
    Added files are covered in full. Never follow a donor symlink into the output.
    """
    states, contents = [], []
    for tree in (official, donor):
        path = tree / name
        if path.is_symlink():
            raise ValueError('Unreviewed symlink: ' + name)
        if path.exists() and not path.is_file():
            raise ValueError('Unreviewed file type: ' + name)
        states.append((path.stat().st_mode & 0o777) if path.exists() else None)
        contents.append(path.read_bytes() if path.exists() else b'')
    old, new = contents
    # Bytes preserve line endings and non-UTF8 data; opcode positions are excluded.
    left, right = old.splitlines(keepends=True), new.splitlines(keepends=True)
    edits = [(left[i:j], right[k:l]) for op, i, j, k, l in
             difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
             if op != 'equal']
    payload = [states, [[[line.hex() for line in x] for x in edit] for edit in edits]]
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()


def validate_delta(official, donor, policy, changes):
    allowed = set(policy['take'])
    if len(allowed) != len(policy['take']) or allowed != set(policy['edit_sha256']):
        raise ValueError('Invalid NSS policy inventory')
    for name in allowed:
        if name.startswith('/') or '..' in Path(name).parts:
            raise ValueError('Invalid NSS policy path: ' + name)
        if name not in changes:
            raise ValueError('Unreviewed NSS edit missing: ' + name)
        if file_delta(official, donor, name) != policy['edit_sha256'][name]:
            raise ValueError('Unreviewed NSS content: ' + name)
    # Watch NSS-owned extension points, not every donor platform difference.
    unexpected = sorted(name for name in changes if name not in allowed and
                        any(re.fullmatch(pattern, name) for pattern in policy['watch_patterns']))
    if unexpected:
        raise ValueError('Unreviewed NSS extension: ' + ', '.join(unexpected[:8]))


def delta(official, donor):
    """Fingerprint changed content, not version tags, line numbers or unchanged lines."""
    changes = {}
    digest = hashlib.sha256()
    for name in sorted(tracked(official) | tracked(donor)):
        a, b = official / name, donor / name
        old = a.read_bytes() if a.is_file() else b''
        new = b.read_bytes() if b.is_file() else b''
        modes = [(p.stat().st_mode & 0o777) if p.exists() else None for p in (a, b)]
        if old == new and modes[0] == modes[1]:
            continue
        changes[name] = modes
        digest.update((name + str(modes)).encode())
        try:
            lines = difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), n=0)
            for line in lines:
                if not line.startswith(('@@', '---', '+++')):
                    digest.update(line.encode())
        except UnicodeDecodeError:
            digest.update(old + b'\0' + new)
    return digest.hexdigest(), changes


def checkout(url, tag, target):
    if target.exists():
        raise ValueError(f'Refusing existing source directory: {target}')
    run('git', 'clone', '--depth', '1', '--branch', tag, url, str(target))


def nss_packages():
    """Use reviewed in-tree recipes; OpenWrt owns git/archive downloads."""
    source = ROOT / 'package/qca-nss'
    for name in ('qca-nss-drv', 'qca-nss-ecm', 'qca-nss-clients'):
        recipe = (source / name / 'Makefile').read_text()
        if 'PKG_SOURCE_PROTO:=git' not in recipe or re.search(r'^PKG_HASH\s*[:?+]?=', recipe, re.M):
            raise ValueError('Expected fixed git source recipe: ' + name)
        for field in ('PKG_SOURCE_URL', 'PKG_SOURCE_DATE', 'PKG_SOURCE_VERSION'):
            if not re.search(r'^' + field + r':=\S+', recipe, re.M):
                raise ValueError('Missing git source field: ' + name + '/' + field)
    return source


def hostapd_muedca_patch(output):
    """Native follow-up to the donor companion, matching backports' nl80211 ABI."""
    source = ROOT / 'patches/hostapd/901-hostapd-muedca-backports-abi.patch'
    dest = output / 'package/network/services/hostapd/patches' / source.name
    if dest.exists():
        raise ValueError('Hostapd MU-EDCA patch collision: ' + str(dest))
    shutil.copy2(source, dest)
    return {str(dest.relative_to(output)): hashlib.sha256(dest.read_bytes()).hexdigest()}


def prepare(official, donor, output, metadata):
    policy = json.loads((ROOT / 'Config/nss-policy.json').read_text())
    fingerprint, changes = delta(official, donor)
    metadata.update(official_commit=run('git', 'rev-parse', 'HEAD', cwd=official),
                    donor_commit=run('git', 'rev-parse', 'HEAD', cwd=donor),
                    delta_sha256=fingerprint, changed_files=len(changes))
    validate_delta(official, donor, policy, changes)
    metadata.update(nss_policy_sha256=hashlib.sha256(
                        (ROOT / 'Config/nss-policy.json').read_bytes()).hexdigest(),
                    selected_edit_sha256=policy['edit_sha256'],
                    excluded_donor_files=sorted(set(changes) - set(policy['take'])))
    for tree in (official, donor):
        if run('git', 'status', '--porcelain', cwd=tree):
            raise ValueError(f'Dirty source tree: {tree}')
    official_kernels = sorted((official / 'target/linux/generic').glob('kernel-*'))
    donor_kernels = sorted((donor / 'target/linux/generic').glob('kernel-*'))
    if len(official_kernels) != 1 or len(donor_kernels) != 1 or official_kernels[0].name != donor_kernels[0].name:
        raise ValueError('Kernel series differ or is ambiguous; port review required')
    if official_kernels[0].read_bytes() != donor_kernels[0].read_bytes():
        raise ValueError('Kernel source versions differ; port review required')
    feeds = (official / 'feeds.conf.default').read_text()
    package_source = nss_packages()
    metadata.update(nss_source='VIKING-style in-tree packages; LiBwrt stable NSS patches; qosmio recipes',
                    nss_recipe_origin='qosmio/nss-packages@0d970dbf0185e3f53709bd803e8a466598023c57',
                    official_feeds=feeds.splitlines(),
                    transplanted_files=policy['take'], validation='source-prepared; not firmware-build-tested')
    if output.exists() and any(output.iterdir()):
        raise ValueError(f'Output must be empty: {output}')
    # A failed copy never leaves a ready marker. Caller must discard incomplete output.
    shutil.copytree(official, output, dirs_exist_ok=True, symlinks=True)
    for name in policy['take']:
        if name not in changes:
            raise ValueError('Reviewed change missing: ' + name)
        source, dest = donor / name, output / name
        if source.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        elif dest.exists():
            dest.unlink()
    metadata['local_patch_sha256'] = hostapd_muedca_patch(output)
    metadata['transplanted_sha256'] = {
        name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        if (output / name).is_file() else None for name in policy['take']}
    config = (output / 'Config.in').read_text()
    if 'source "config/Config-ipq.in"' not in config:
        (output / 'Config.in').write_text(config + '\nsource "config/Config-ipq.in"\n')
    package_files = {}
    for name in ('qca-nss-drv', 'qca-nss-ecm', 'qca-nss-clients', 'nss-firmware'):
        dest = output / 'package/qca-nss' / Path(name).name
        shutil.copytree(package_source / name, dest)
        for path in sorted(dest.rglob('*')):
            if path.is_file():
                package_files[str(path.relative_to(output))] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata['nss_package_files'] = package_files
    metadata['viking_reference'] = '90448eeb2b8f5d172caedfe6d96ab3bacb058c09'
    (output / 'feeds.conf.default').write_text(feeds)
    (output / 'source-lock.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--resolve-only', action='store_true')
    args = parser.parse_args()
    metadata = resolve()
    args.sources.mkdir(parents=True, exist_ok=True)
    (args.sources / 'resolved.json').write_text(json.dumps(metadata, indent=2) + '\n')
    if args.resolve_only:
        print(json.dumps(metadata, indent=2))
        return
    official, donor = args.sources / 'official', args.sources / 'libwrt'
    for tree, url, key in ((official, OFFICIAL, 'official_tag'), (donor, DONOR, 'donor_tag')):
        if not tree.exists():
            checkout(url, metadata[key], tree)
        if run('git', 'describe', '--tags', '--exact-match', cwd=tree) != metadata[key]:
            raise ValueError('Cached sources do not match current release; use a new --sources directory')
        if run('git', 'remote', 'get-url', 'origin', cwd=tree) != url:
            raise ValueError('Unexpected cached source origin')
        remote = run('git', 'ls-remote', url, 'refs/tags/' + metadata[key], 'refs/tags/' + metadata[key] + '^{}')
        revisions = [line.split()[0] for line in remote.splitlines()]
        if run('git', 'rev-parse', 'HEAD', cwd=tree) not in revisions:
            raise ValueError('Cached tag no longer matches remote')
    prepare(official, donor, args.output, metadata)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
