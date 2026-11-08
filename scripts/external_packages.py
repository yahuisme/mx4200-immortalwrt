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
    'eamonxg': {
        'url': 'https://openwrt.eamonxg.fun/snapshots/apk',
        'key': 'https://openwrt.eamonxg.fun/eamonxg.pem',
        'key_sha256': 'b1ca40fd0362f7975e67d328d20a06e5e33a83bfa397cd3dc66251c05bef9354',
        'packages': ['luci-theme-aurora', 'luci-app-aurora-config', 'luci-i18n-aurora-config-zh-cn'],
    },
}
ARCH = 'aarch64_cortex-a53'


def replace_once(text, old, new, path):
    """Validate a single native boundary without writing partial preparation."""
    if text.count(new) == 1 and text.count(old) == new.count(old):
        return text
    if new in text or text.count(old) != 1:
        raise ValueError(f'Unsupported upstream assembly boundary: {path}')
    return text.replace(old, new, 1)


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def reviewed_version(root):
    """Accept numeric stable sources only, with unchanged native APK boundaries.

    Latest-release selection belongs to the official-source resolver, not this
    compatibility check. Future stable versions need no version-list update.
    """
    text = (root / 'include/version.mk').read_text()
    assignments = re.findall(r'^VERSION_NUMBER\s*[:+?]?=.*$', text, re.M)
    numeric = r'([0-9]+\.[0-9]+\.[0-9]+)'
    version = None
    if len(assignments) == 1:
        version = re.fullmatch(r'VERSION_NUMBER:=' + numeric, assignments[0])
    elif (len(assignments) == 2 and
          assignments[0] == 'VERSION_NUMBER:=$(call qstrip,$(CONFIG_VERSION_NUMBER))'):
        version = re.fullmatch(r'VERSION_NUMBER:=\$\(if \$\(VERSION_NUMBER\),\$\(VERSION_NUMBER\),' +
                               numeric + r'\)', assignments[1])
    if version is None:
        raise ValueError('External APK feeds require numeric ImmortalWrt stable')
    config_path = root / '.config'
    config = config_path.read_text() if config_path.exists() else ''
    overrides = re.findall(r'^CONFIG_VERSION_NUMBER=(.*)$', config, re.M)
    if len(overrides) > 1 or (overrides and overrides[0] not in ('""', '"' + version[1] + '"')):
        raise ValueError('External APK feeds require numeric ImmortalWrt stable without version override')
    assembly_updates(root)  # Read-only preflight also protects the custom.sh caller.


def assembly_updates(root):
    """Stage every replacement in memory; unsupported sources cannot partially write."""
    texts = {name: (root / name).read_text() for name in ('include/rootfs.mk', 'package/Makefile')}
    common = texts['package/Makefile']
    image = (root / 'include/image.mk').read_text()
    # Keep per-device resolution on the same shared offline/trusted helper.
    for boundary in ('$(call apk,$(mkfs_cur_target_dir)) --no-scripts',
                     '$(call prepare_rootfs,$(mkfs_cur_target_dir),$(TOPDIR)/files)'):
        if image.count(boundary) != 1:
            raise ValueError('Unsupported upstream assembly boundary: include/image.mk')
    for boundary in ('\t\t--repositories-file /dev/null --repository file://$(PACKAGE_DIR_ALL)/packages.adb \\\n',
                     '\t\t$(if $(CONFIG_SIGNED_PACKAGES),,--allow-untrusted) \\\n',
                     *('"' + name + '=$(shell cat $(STAGING_DIR)/' + name + '.version)"'
                       for name in ('base-files', 'libc', 'kernel'))):
        if common.count(boundary) != 1:
            raise ValueError('Unsupported upstream assembly boundary: package/Makefile')
    # Reviewed stable has a direct install recipe, not snapshot's cached/eval path.
    if ('rootfs_cache' in common or '$(eval ROOTFS_KEY' in common or
            common.count('$(curdir)/install: $(TMP_DIR)/.build $(curdir)/merge $(curdir)/merge-index\n') != 1):
        raise ValueError('Unsupported upstream assembly boundary: package/Makefile')
    def replace(name, old, new):
        texts[name] = replace_once(texts[name], old, new, root / name)
    # Both package/install and per-device add/del call this shared helper.
    replace('include/rootfs.mk', 'apk = \\\n',
            'include $(TOPDIR)/.external-packages.mk\n\napk = \\\n')
    replace('include/rootfs.mk',
            '\t--keys-dir $(if $(APK_KEYS),$(APK_KEYS),$(TOPDIR)) \\\n',
            '\t--keys-dir $(TOPDIR)/.external-packages/keys \\\n'
            '\t--no-network $(MX_EXTERNAL_REPOSITORIES) \\\n')
    # Stable has no cache-key eval; snapshot verification must precede native add.
    replace('package/Makefile',
            '\t$(call apk,$(TARGET_DIR)) add --no-cache --initdb --no-scripts --arch $(ARCH_PACKAGES) \\\n',
            '\tpython3 /cache-scripts/external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk\n'
            '\t$(call apk,$(TARGET_DIR)) add --no-cache --initdb --no-scripts --arch $(ARCH_PACKAGES) \\\n')
    replace('package/Makefile',
            '\t\t$$(cat $(TMP_DIR)/apk_install_list) \\\n',
            '\t\t$$(cat $(TMP_DIR)/apk_install_list) $(MX_EXTERNAL_PACKAGES) \\\n')
    replace('include/rootfs.mk',
            '\t$(call mklibs,$(1))\n',
            '\t$(call mklibs,$(1))\n'
            '\tpython3 /cache-scripts/external_packages.py verify-root $(1) $(TOPDIR)/.external-packages/provenance.json\n')
    return texts


def prepare(root):
    root = Path(root).resolve()
    reviewed_version(root)  # Reject version/config/assembly drift before any writes.
    updates = assembly_updates(root)
    packages = ' '.join(f'{p}@{tag}' for tag, repo in REPOSITORIES.items() for p in repo['packages'])
    repositories = ' '.join('--repository-config "@' + tag + ' file://$(TOPDIR)/.external-packages/' +
                            tag + '/packages.adb"' for tag in REPOSITORIES)
    for name, text in updates.items():
        put(root, name, text)
    put(root, '.external-packages.mk', 'MX_EXTERNAL_PACKAGES:=' + packages + '\n' +
        'MX_EXTERNAL_REPOSITORIES:=' + repositories + '\n')
    # Runtime entries are editable by LuCI and contain no builder paths.
    put(root, 'files/etc/apk/repositories.d/customfeeds.list', ''.join(
        f'@{tag} {repo["url"]}/packages.adb\n' for tag, repo in REPOSITORIES.items()))


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
    reviewed_version(root)  # Recheck at assembly even after successful preparation.
    if (re.findall(r'^CONFIG_USE_APK=(.*)$', config, re.M) != ['y'] or
            re.findall(r'^CONFIG_TARGET_ARCH_PACKAGES=(.*)$', config, re.M) != ['"' + ARCH + '"']):
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
    for name in ('luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box'):
        if not installed.get(name):
            raise ValueError('Missing source-built proxy package: ' + name)
    for name in ('etc/config/homeproxy', 'usr/share/luci/menu.d/luci-app-homeproxy.json',
                 'usr/lib/lua/luci/i18n/homeproxy.zh-cn.lmo'):
        if not (root / name).is_file() or not (root / name).stat().st_size:
            raise ValueError('Missing HomeProxy runtime file: ' + name)
    core = root / 'usr/bin/sing-box'
    if not core.is_file() or not core.stat().st_size or not os.access(core, os.X_OK):
        raise ValueError('Missing executable sing-box core')
    for name in ('luci-app-cpufreq', 'luci-i18n-cpufreq-zh-cn'):
        if not installed.get(name):
            raise ValueError('Missing CPU performance package: ' + name)
    for name in ('www/luci-static/resources/view/cpufreq.js',
                 'usr/share/rpcd/acl.d/luci-app-cpufreq.json',
                 'usr/share/luci/menu.d/luci-app-cpufreq.json',
                 'usr/lib/lua/luci/i18n/cpufreq.zh-cn.lmo'):
        if not (root / name).is_file() or not (root / name).stat().st_size:
            raise ValueError('Missing CPU performance runtime file: ' + name)
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


if __name__ == '__main__':
    if sys.argv[1] == 'preflight':
        reviewed_version(Path(sys.argv[2]).resolve())
    elif sys.argv[1] == 'prepare':
        prepare(sys.argv[2])
    elif sys.argv[1] == 'snapshot':
        snapshot(*sys.argv[2:])
    elif sys.argv[1] == 'verify-root':
        verify_root(*sys.argv[2:])
    else:
        sys.exit('Unknown external package operation')
