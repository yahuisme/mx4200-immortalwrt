#!/usr/bin/env python3
"""Resolve and verify pristine official RAM configuration, not a symbol subset."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


SEED = {
    'CONFIG_TARGET_qualcommax': 'y',
    'CONFIG_TARGET_qualcommax_ipq807x': 'y',
    'CONFIG_TARGET_qualcommax_ipq807x_DEVICE_linksys_homewrk': 'y',
    'CONFIG_TARGET_ROOTFS_INITRAMFS': 'y',
    'CONFIG_PACKAGE_luci': 'y',
    'CONFIG_LUCI_LANG_zh_Hans': 'y',
}
CANONICAL_SEED = ''.join(f'{key}={value}\n' for key, value in SEED.items())
HOST_FRAGMENT = '''CONFIG_CCACHE=y
CONFIG_CCACHE_DIR="/ghcache"
# CONFIG_GOLANG_BUILD_BOOTSTRAP is not set
CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT="/usr/lib/go"
'''
# Exact host-only exceptions, never a prefix blacklist. Official Config-devel.in
# makes CCACHE_DIR conditional on CCACHE. packages/lang/golang/golang-bootstrap/
# Config.in has independent empty-cache/false defaults when its menu becomes
# visible. No Go package, target compiler option or arbitrary directory is exempt.
HOST_VALUES = {
    'CONFIG_CCACHE': 'y',
    'CONFIG_CCACHE_DIR': '"/ghcache"',
    'CONFIG_GOLANG_BUILD_BOOTSTRAP': 'n',
    'CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT': '"/usr/lib/go"',
}
HOST_DERIVED = {
    'CONFIG_GOLANG_BUILD_CACHE_DIR': '""',
}


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def config_values(text):
    """Ignore layout/comments; absent, explicit n and unset all mean disabled.

    Reject duplicate or malformed assignments instead of silently using the
    last value. String contents (including '#') and all enabled values matter.
    """
    values = {}
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        unset = re.fullmatch(r'# (CONFIG_[A-Za-z0-9_+.-]+) is not set', line)
        if unset:
            key, value = unset[1], 'n'
        elif line.startswith('#'):
            continue
        else:
            match = re.fullmatch(r'(CONFIG_[A-Za-z0-9_+.-]+)\s*=\s*(y|m|n|-?[0-9]+|0x[0-9a-fA-F]+|"(?:[^"\\]|\\.)*")', line)
            if not match:
                raise ValueError('Malformed RAM Kconfig row: ' + line)
            key, value = match.groups()
        if key in seen:
            raise ValueError('Duplicate RAM Kconfig symbol: ' + key)
        seen.add(key)
        if value != 'n':
            values[key] = value
    return values


def recipe_text():
    recipe = Path(__file__).resolve().parents[1] / 'user/ramboot/config.diff'
    if not recipe.is_file():
        recipe = Path('/bld/user/ramboot/config.diff')
    text = recipe.read_text()
    if config_values(text) != SEED:
        raise ValueError('RAM profile must add only Chinese LuCI to official HomeWRK')
    return text


def identity(root, main):
    sha = git(root, 'rev-parse', '--verify', 'HEAD')
    if sha != git(main, 'rev-parse', '--verify', 'HEAD'):
        raise ValueError('RAM and main official source identities differ')
    if git(root, 'remote', 'get-url', 'origin') != 'https://github.com/immortalwrt/immortalwrt.git':
        raise ValueError('RAM source is not the official origin')
    if git(root, 'diff', 'HEAD', '--'):
        raise ValueError('RAM official tracked sources were modified')
    for name in ('files', '.external-packages', '.external-packages.mk', '.custom-revisions.tsv'):
        if (root / name).exists() or (root / name).is_symlink():
            raise ValueError('Project customization leaked into RAM source: ' + name)
    feed_text = (root / 'feeds.conf').read_text()
    if feed_text.strip() != git(root, 'show', 'HEAD:feeds.conf.default'):
        raise ValueError('RAM feeds configuration differs from official source')
    feeds = []
    for row in feed_text.splitlines():
        parts = row.split()
        if not parts or parts[0] not in ('src-git', 'src-git-full'):
            continue
        if len(parts) != 3:
            raise ValueError('Invalid official feed row')
        name, url = parts[1:]
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or any(f['name'] == name for f in feeds):
            raise ValueError('Invalid official feed name')
        feed, main_feed = root / 'feeds' / name, main / 'feeds' / name
        if not (feed / '.git').exists() or not (main_feed / '.git').exists():
            raise ValueError('Missing independent Git feed: ' + name)
        commit = git(feed, 'rev-parse', '--verify', 'HEAD')
        origin = re.split('[;^]', url)[0]
        if (commit != git(main_feed, 'rev-parse', '--verify', 'HEAD') or
                git(feed, 'diff', 'HEAD', '--') or git(feed, 'remote', 'get-url', 'origin') != origin):
            raise ValueError('RAM feed is not pristine matching official objects: ' + name)
        feeds.append(dict(name=name, sha=commit, origin=origin))
    if not feeds:
        raise ValueError('No official RAM feeds')
    return dict(source_sha=sha, feeds=feeds, feeds_config_sha256=digest(feed_text.encode()))


def regular_bytes(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError('Missing/nonregular RAM baseline or config: ' + str(path))
    return path.read_bytes()


def verify(root, main, record, baseline=None):
    root, main = Path(root), Path(main)
    provenance = identity(root, main)
    recipe_text()
    if baseline is None:
        raise ValueError('Native resolved RAM baseline is mandatory')
    baseline = Path(baseline)
    actual = root / '.config'
    raw = regular_bytes(baseline)
    regular_bytes(actual)
    if baseline.resolve() == actual.resolve() or baseline.samefile(actual):
        raise ValueError('RAM baseline cannot be the final config')
    metadata = json.loads(regular_bytes(str(baseline) + '.json'))
    expected_metadata = dict(provenance, seed_sha256=digest(CANONICAL_SEED.encode()),
                             config_sha256=digest(raw), resolver='make defconfig', schema=1)
    if metadata != expected_metadata:
        raise ValueError('RAM baseline source/feed/seed/config identity mismatch')
    reference, config = config_values(raw.decode()), config_values(regular_bytes(actual).decode())
    if any(reference.get(key) != value or config.get(key) != value for key, value in SEED.items()):
        raise ValueError('RAM resolved config lost requested HomeWRK/LuCI symbols')
    changed = []
    allowed = []
    for key in sorted(reference.keys() | config.keys()):
        old, new = reference.get(key, 'n'), config.get(key, 'n')
        if old == new:
            continue
        if key in HOST_VALUES and new == HOST_VALUES[key]:
            allowed.append(key)
        elif key in HOST_DERIVED and key not in reference and new == HOST_DERIVED[key]:
            allowed.append(key)
        else:
            changed.append(f'{key}: {old} -> {new}')
    if changed:
        raise ValueError('RAM differs from official resolved baseline: ' + '; '.join(changed))
    revision = subprocess.check_output([str(root / 'scripts/getver.sh')], cwd=root, text=True).strip()
    if not re.fullmatch(r'r[1-9][0-9]*-[0-9a-f]+', revision):
        raise ValueError('RAM official revision is not a nonzero native revision: ' + revision)
    result = dict(provenance, revision=revision, config_sha256=digest(actual.read_bytes()),
                  baseline_sha256=digest(raw), baseline_seed_sha256=digest(CANONICAL_SEED.encode()),
                  baseline_resolver='make defconfig', host_only_differences=allowed,
                  pristine=True, customization='Chinese LuCI only')
    Path(record).write_text(json.dumps(result, indent=2) + '\n')
    return result


def configure(root, main, record):
    """Trusted production producer: independent canonical seed, then host controls.

    Both passes use the same native Kconfig and exact source/feed objects. Never
    copy an arbitrary final config to become its own reference. Fail if stale
    config/baseline exists; retain the baseline beside the build record.
    """
    root, main, record = Path(root), Path(main), Path(record)
    provenance = identity(root, main)
    requested = recipe_text()
    baseline = record.with_name('ramboot-baseline.config')
    metadata = Path(str(baseline) + '.json')
    if any(path.exists() or path.is_symlink() for path in (root / '.config', baseline, metadata)):
        raise ValueError('RAM configuration/baseline must be generated fresh')
    (root / '.config').write_text(CANONICAL_SEED)
    subprocess.run(['make', 'defconfig'], cwd=root, check=True)
    raw = regular_bytes(root / '.config')
    # The producer owns these new files; the verifier binds exact native output
    # to source, feeds, seed and digest, rather than trusting its filename.
    with baseline.open('xb') as stream:
        stream.write(raw)
    with metadata.open('x') as stream:
        json.dump(dict(provenance, seed_sha256=digest(CANONICAL_SEED.encode()),
                       config_sha256=digest(raw), resolver='make defconfig', schema=1), stream, indent=2)
    (root / '.config').write_text(requested.rstrip() + '\n' + HOST_FRAGMENT)
    subprocess.run(['make', 'defconfig'], cwd=root, check=True)
    return verify(root, main, record, baseline)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--configure', action='store_true', help='produce fresh native baseline and final config')
    mode.add_argument('--baseline', type=Path, help='verify an existing producer-bound baseline')
    parser.add_argument('source', type=Path)
    parser.add_argument('main_source', type=Path)
    parser.add_argument('record', type=Path)
    args = parser.parse_args()
    result = (configure(args.source, args.main_source, args.record) if args.configure else
              verify(args.source, args.main_source, args.record, args.baseline))
    print(json.dumps(result))
