#!/usr/bin/env python3
"""Install signed upstream APKs through the native rootfs package manager."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


REPOSITORIES = {
    'daeuniverse': {
        'url': 'https://openwrt.daeuniverse.org/25.12/packages/aarch64_cortex-a53',
        'key': 'https://openwrt.daeuniverse.org/public-key.pem',
        'key_sha256': '5aae30568b7e08f86ea3e72a19fa281d835ba4eff8ab38849abcd2b0884c6cd5',
        'packages': ['honk', 'luci-app-honk', 'luci-lib-daeuniverse',
                     'luci-i18n-daeuniverse-zh-cn', 'vmlinux-btf-builtin'],
    },
    'eamonxg': {
        'url': 'https://openwrt.eamonxg.fun/snapshots/apk',
        'key': 'https://openwrt.eamonxg.fun/eamonxg.pem',
        'key_sha256': 'b1ca40fd0362f7975e67d328d20a06e5e33a83bfa397cd3dc66251c05bef9354',
        'packages': ['luci-theme-aurora', 'luci-app-aurora-config', 'luci-i18n-aurora-config-zh-cn'],
    },
}
ARCH = 'aarch64_cortex-a53'


def replace_once(path, old, new):
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        raise ValueError(f'Unsupported upstream assembly boundary: {path}')
    path.write_text(text.replace(old, new, 1))


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def prepare(root):
    root = Path(root).resolve()
    packages = ' '.join(f'{p}@{tag}' for tag, repo in REPOSITORIES.items() for p in repo['packages'])
    repositories = ' '.join('--repository-config "@' + tag + ' file://$(TOPDIR)/.external-packages/' +
                            tag + '/packages.adb"' for tag in REPOSITORIES)
    put(root, '.external-packages.mk', 'MX_EXTERNAL_PACKAGES:=' + packages + '\n' +
        'MX_EXTERNAL_REPOSITORIES:=' + repositories + '\n')
    # Both package/install and per-device add/del call this shared helper.
    replace_once(root / 'include/rootfs.mk', 'apk = \\\n',
                 'include $(TOPDIR)/.external-packages.mk\n\napk = \\\n')
    replace_once(root / 'include/rootfs.mk',
                 '\t--keys-dir $(if $(APK_KEYS),$(APK_KEYS),$(TOPDIR)) \\\n',
                 '\t--keys-dir $(TOPDIR)/.external-packages/keys \\\n'
                 '\t--no-network $(MX_EXTERNAL_REPOSITORIES) \\\n')
    replace_once(root / 'package/Makefile',
                 '\t$(call apk,$(TARGET_DIR)) add --no-cache --initdb --no-scripts --arch $(ARCH_PACKAGES) \\\n',
                 '\tpython3 /cache-scripts/external_packages.py verify-kernel $(TOPDIR)\n'
                 '\tpython3 /cache-scripts/external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk\n'
                 '\t$(call apk,$(TARGET_DIR)) add --no-cache --initdb --no-scripts --arch $(ARCH_PACKAGES) \\\n')
    replace_once(root / 'package/Makefile',
                 '\t\t$$(cat $(TMP_DIR)/apk_install_list) \\\n',
                 '\t\t$$(cat $(TMP_DIR)/apk_install_list) $(MX_EXTERNAL_PACKAGES) \\\n')
    replace_once(root / 'include/rootfs.mk',
                 '\t$(call mklibs,$(1))\n',
                 '\t$(call mklibs,$(1))\n'
                 '\tpython3 /cache-scripts/external_packages.py verify-root $(1) $(TOPDIR)/.external-packages/provenance.json\n')
    # Runtime entries are editable by LuCI and contain no builder paths.
    put(root, 'files/etc/apk/repositories.d/customfeeds.list', ''.join(
        f'@{tag} {repo["url"]}/packages.adb\n' for tag, repo in REPOSITORIES.items()))
    config = root / 'files/etc/honk/config.dae'
    if config.is_file():
        config.parent.chmod(0o700)
        config.chmod(0o600)


def download(url, path):
    subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20',
                    '--max-time', '180', '--output', str(path), url], check=True)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(root, apk, repositories=None):
    root, apk = Path(root).resolve(), str(Path(apk).resolve())
    repositories = repositories or REPOSITORIES
    config = (root / '.config').read_text()
    version = (root / 'include/version.mk').read_text()
    if not re.search(r'^VERSION_NUMBER:=.*25\.12\.[0-9]+\)', version, re.M) and not re.search(
            r'^VERSION_NUMBER:=25\.12\.[0-9]+$', version, re.M):
        raise ValueError('External APK feeds require reviewed ImmortalWrt 25.12')
    if 'CONFIG_USE_APK=y' not in config or f'CONFIG_TARGET_ARCH_PACKAGES="{ARCH}"' not in config:
        raise ValueError('External APK feeds require APK and aarch64_cortex-a53')
    destination = root / '.external-packages'
    destination.mkdir(exist_ok=True)
    # No valid provenance survives a failed refresh or a truncated download.
    (destination / 'provenance.json').unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='external-apk-', dir=root) as directory:
        stage = Path(directory)
        keys = stage / 'keys'
        keys.mkdir()
        (stage / 'resolver').mkdir()
        # Include the native build key; foreign kernel repositories are never used.
        for key in root.glob('*.pem'):
            if 'PRIVATE KEY' not in key.read_text():
                shutil.copyfile(key, keys / key.name)
        rows, feeds = [], []
        for tag, repo in repositories.items():
            key = keys / (tag + '.pem')
            download(repo['key'], key)
            if digest(key) != repo['key_sha256']:
                raise ValueError('Upstream signing key changed: ' + tag)
            mirror = stage / tag
            mirror.mkdir()
            index = mirror / 'packages.adb'
            download(repo['url'] + '/packages.adb', index)
            command = [apk, '--root', str(stage / 'resolver'), '--keys-dir', str(keys),
                       '--arch', ARCH, '--repositories-file', '/dev/null', '--no-cache', '--no-logfile']
            subprocess.run(command + ['verify', str(index)], check=True)
            data = json.loads(subprocess.check_output(command + ['adbdump', '--format', 'json', str(index)], text=True))
            selected = []
            for name in repo['packages']:
                matches = [p for p in data['packages'] if p['name'] == name]
                if len(matches) != 1 or matches[0]['arch'] not in (ARCH, 'noarch'):
                    raise ValueError('Unavailable or wrong-architecture APK: ' + name)
                metadata = matches[0]
                filename = name + '-' + metadata['version'] + '.apk'
                if '/' in filename or not re.fullmatch(r'[A-Za-z0-9_.+~\-]+\.apk', filename):
                    raise ValueError('Invalid APK filename: ' + filename)
                download(repo['url'] + '/' + filename, mirror / filename)
                selected.append(dict(name=name, version=metadata['version'], arch=metadata['arch'],
                                     repository=tag, filename=filename,
                                     sha256=digest(mirror / filename)))
            # Fetch through the original signed index verifies package identity and
            # data hashes too, including upstream APKs that are not individually signed.
            verified = stage / ('verified-' + tag)
            verified.mkdir()
            subprocess.run(command + ['--repository', mirror.as_uri() + '/packages.adb',
                                      '--no-network', 'fetch', '--output', str(verified), *repo['packages']], check=True)
            for row in selected:
                if digest(verified / row['filename']) != row['sha256']:
                    raise ValueError('APK byte verification failed: ' + row['name'])
            rows.extend(selected)
            feeds.append(dict(name=tag, url=repo['url'], index_sha256=digest(index),
                              key_sha256=digest(key)))
        record = dict(version=1, architecture=ARCH, repositories=feeds, packages=rows)
        # Publish only a complete, verified snapshot. Every device uses these bytes.
        for name in [*repositories, 'keys']:
            target = destination / name
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(stage / name), target)
        for tag in repositories:
            key = destination / 'keys' / (tag + '.pem')
            target = root / 'files/etc/apk/keys' / key.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(key, target)
        (destination / 'provenance.json').write_text(json.dumps(record, indent=2) + '\n')


def verify_root(root, provenance):
    root = Path(root)
    record = json.loads(Path(provenance).read_text())
    installed = {}
    for block in (root / 'lib/apk/db/installed').read_text().split('\n\n'):
        fields = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
        if 'P' in fields:
            installed[fields['P']] = fields.get('V')
    world = (root / 'etc/apk/world').read_text().splitlines()
    retired = ('luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box')
    for name in retired:
        if name in installed or any(re.split(r'[@=~<>]', line)[0] == name for line in world):
            raise ValueError('Retired proxy package in rootfs: ' + name)
    for row in record['packages']:
        if installed.get(row['name']) != row['version']:
            raise ValueError('Missing or wrong official APK version: ' + row['name'])
        if row['name'] + '@' + row['repository'] not in world:
            raise ValueError('Missing updatable tagged world constraint: ' + row['name'])
    feeds = (root / 'etc/apk/repositories.d/customfeeds.list').read_text()
    if 'file://' in feeds:
        raise ValueError('Build-only repository leaked into firmware')
    for feed in record['repositories']:
        if f'@{feed["name"]} {REPOSITORIES[feed["name"]]["url"]}/packages.adb' not in feeds:
            raise ValueError('Missing runtime repository: ' + feed['name'])
        if digest(root / 'etc/apk/keys' / (feed['name'] + '.pem')) != feed['key_sha256']:
            raise ValueError('Missing or wrong runtime signing key: ' + feed['name'])
    return installed

def verify_kernel(root):
    configs = list(Path(root).glob('build_dir/target-*/linux-qualcommax_ipq807x/linux-*/.config'))
    if len(configs) != 1:
        raise ValueError('Expected one compiled MX4200 kernel configuration')
    values = configs[0].read_text().splitlines()
    for symbol in ('BPF', 'BPF_SYSCALL', 'BPF_JIT', 'CGROUPS', 'CGROUP_BPF',
                   'NET_NS', 'NET_SCHED', 'NET_CLS_ACT', 'NET_XGRESS', 'DEBUG_INFO_BTF'):
        if 'CONFIG_' + symbol + '=y' not in values:
            raise ValueError('Required Honk kernel capability missing: ' + symbol)
    for symbol in ('NF_TABLES', 'NF_TABLES_INET', 'NFT_CT', 'NFT_QUEUE', 'NETFILTER_NETLINK_QUEUE'):
        if not any('CONFIG_' + symbol + '=' + value in values for value in ('y', 'm')):
            raise ValueError('Required Honk kernel capability missing: ' + symbol)


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        prepare(sys.argv[2])
    elif sys.argv[1] == 'snapshot':
        snapshot(*sys.argv[2:])
    elif sys.argv[1] == 'verify-root':
        verify_root(*sys.argv[2:])
    elif sys.argv[1] == 'verify-kernel':
        verify_kernel(*sys.argv[2:])
    else:
        sys.exit('Unknown external package operation')
