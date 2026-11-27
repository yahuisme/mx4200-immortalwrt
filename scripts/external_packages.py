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
RUNTIME_FEEDS = 'etc/apk/repositories.d/customfeeds.list'


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


def reviewed_version(root, config):
    """Recognize the official Snapshot and numeric stable version templates.

    Latest-release selection belongs to the official-source resolver, not this
    compatibility check. Future stable versions need no version-list update.
    """
    text = (root / 'include/version.mk').read_text()
    assignments = re.findall(r'^VERSION_NUMBER\s*[:+?]?=.*$', text, re.M)
    number = r'(SNAPSHOT|[0-9]+\.[0-9]+\.[0-9]+)'
    version = None
    if len(assignments) == 1:
        version = re.fullmatch(r'VERSION_NUMBER:=' + number, assignments[0])
    elif (len(assignments) == 2 and
          assignments[0] == 'VERSION_NUMBER:=$(call qstrip,$(CONFIG_VERSION_NUMBER))'):
        version = re.fullmatch(r'VERSION_NUMBER:=\$\(if \$\(VERSION_NUMBER\),\$\(VERSION_NUMBER\),' +
                               number + r'\)', assignments[1])
    if version is None:
        raise ValueError('External APK feeds require numeric ImmortalWrt stable or reviewed ImmortalWrt Snapshot')
    overrides = re.findall(r'^CONFIG_VERSION_NUMBER=(.*)$', config, re.M)
    if len(overrides) > 1 or (overrides and overrides[0] not in ('""', '"' + version[1] + '"')):
        raise ValueError('External APK feeds require numeric ImmortalWrt stable or reviewed ImmortalWrt Snapshot without version override')
    return version[1]


def assembly_updates(root, version):
    """Stage every replacement in memory; unsupported sources cannot partially write."""
    texts = {name: (root / name).read_text() for name in ('include/rootfs.mk', 'package/Makefile', 'include/image.mk')}
    if version == 'SNAPSHOT':
        return snapshot_assembly_updates(root, texts)
    common = texts['package/Makefile']
    image = texts.pop('include/image.mk')
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


def snapshot_assembly_updates(root, texts):
    common, shared, image = 'package/Makefile', 'include/rootfs.mk', 'include/image.mk'

    def replace(path, old, new):
        texts[path] = replace_once(texts[path], old, new, root / path)

    # Fail closed on changes to the cached installer and its native constraints.
    for boundary in ('define rootfs_cache_key\n', 'define rootfs_cache_restore\n',
                     'define apk_install_rootfs\n', 'APK_INSTALL_ARGS = \\\n',
                     '\tbase-files=$(shell cat $(STAGING_DIR)/base-files.version) \\\n',
                     '\tlibc=$(shell cat $(STAGING_DIR)/libc.version) \\\n',
                     '\tkernel=$(subst -rc,_rc,$(shell cat $(STAGING_DIR)/kernel.version))\n',
                     '\t\t--repositories-file /dev/null --repository file://$(PACKAGE_DIR_ALL)/packages.adb \\\n',
                     '\t\t$(if $(CONFIG_SIGNED_PACKAGES),,--allow-untrusted) \\\n',
                     '\t$(eval ROOTFS_KEY:=$(call rootfs_cache_key,$(APK_INSTALL_ARGS)))\n',
                     '\t$(if $(filter $(ROOTFS_KEY),$(shell cat $(ROOTFS_CACHE)/key 2>/dev/null)),$(rootfs_cache_restore),$(apk_install_rootfs))\n'):
        if texts[common].count(boundary) != 1:
            raise ValueError(f'Unsupported upstream assembly boundary: {root / common}')

    # The prerequisite must finish before GNU make expands ROOTFS_KEY (not just
    # before the shell runs apk add). Include the frozen signed inputs in the key.
    install_inputs = '$(TMP_DIR)/.build $(curdir)/merge $(curdir)/merge-index'
    install_rule = '$(curdir)/install: ' + install_inputs
    replace(common, install_rule + '\n',
            '.PHONY: mx-external-packages\nmx-external-packages: ' + install_inputs + '\n'
            '\tpython3 /cache-scripts/external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk\n\n'
            + install_rule + ' mx-external-packages\n')
    replace(common, '\t\t$(INCLUDE_DIR)/rootfs.mk $(TOPDIR)/package/Makefile; \\\n',
            '\t\t$(INCLUDE_DIR)/rootfs.mk $(TOPDIR)/package/Makefile \\\n'
            '\t\t$(TOPDIR)/.external-packages.mk $(TOPDIR)/.external-packages/provenance.json \\\n'
            '\t\t$(TOPDIR)/.external-packages/files/etc/apk/repositories.d/customfeeds.list; \\\n')
    replace(common, '\t$(call apk,$(TARGET_DIR)) add --no-cache --initdb --no-scripts --arch $(ARCH_PACKAGES) \\\n',
            '\t$(call apk,$(TARGET_DIR),mx-external) add --no-cache --initdb --no-scripts --arch $(ARCH_PACKAGES) \\\n')
    replace(common, '\t\t$$(cat $(TMP_DIR)/apk_install_list)\n',
            '\t\t$$(cat $(TMP_DIR)/apk_install_list) $(MX_EXTERNAL_PACKAGES)\n')
    replace(common, '\t$(CP) $(TARGET_DIR) $(TARGET_DIR_ORIG)\n'
            '\t$(call prepare_rootfs,$(TARGET_DIR),$(TOPDIR)/files)\n\trm -rf $(ROOTFS_CACHE)\n',
            '\t$(CP) $(TARGET_DIR) $(TARGET_DIR_ORIG)\n'
            '\t$(call prepare_rootfs,$(TARGET_DIR),$(TOPDIR)/files,,mx-external)\n\trm -rf $(ROOTFS_CACHE)\n')
    replace(common, '\tcp -a $(ROOTFS_CACHE)/root.orig $(TARGET_DIR_ORIG)\n',
            '\tcp -a $(ROOTFS_CACHE)/root.orig $(TARGET_DIR_ORIG)\n'
            '\tpython3 /cache-scripts/external_packages.py verify-root $(TARGET_DIR) $(TOPDIR)/.external-packages/provenance.json\n')

    # Only formal callers opt in. The native APK helper and prepare_rootfs can
    # still be used independently by an initramfs installed from official defaults.
    replace(shared, 'apk = \\\n', 'include $(TOPDIR)/.external-packages.mk\n\napk = \\\n')
    replace(shared, '\t--keys-dir $(if $(APK_KEYS),$(APK_KEYS),$(TOPDIR)) \\\n',
            '\t--keys-dir $(if $(filter mx-external,$(2)),$(TOPDIR)/.external-packages/keys,$(if $(APK_KEYS),$(APK_KEYS),$(TOPDIR))) \\\n'
            '\t$(if $(filter mx-external,$(2)),--no-network $(MX_EXTERNAL_REPOSITORIES)) \\\n')
    replace(shared, '\t@mkdir -p $(1)/etc/rc.d\n',
            '\t$(if $(filter mx-external,$(4)),$(call file_copy,$(TOPDIR)/.external-packages/files/.,$(1)))\n'
            '\t@mkdir -p $(1)/etc/rc.d\n')
    replace(shared, '\t$(call mklibs,$(1))\n',
            '\t$(call mklibs,$(1))\n'
            '\t$(if $(filter mx-external,$(4)),python3 /cache-scripts/external_packages.py verify-root $(1) $(TOPDIR)/.external-packages/provenance.json)\n')
    replace(image, '\t$(call apk,$(mkfs_cur_target_dir)) --no-scripts \\\n'
            '\t\t--repositories-file /dev/null --repository file://$(PACKAGE_DIR_ALL)/packages.adb\n',
            '\t$(call apk,$(mkfs_cur_target_dir),mx-external) --no-scripts \\\n'
            '\t\t--repositories-file /dev/null --repository file://$(PACKAGE_DIR_ALL)/packages.adb\n')
    replace(image, '\t$(call prepare_rootfs,$(mkfs_cur_target_dir),$(TOPDIR)/files)\n',
            '\t$(call prepare_rootfs,$(mkfs_cur_target_dir),$(TOPDIR)/files,,mx-external)\n'
            '\tpython3 /cache-scripts/external_packages.py verify-advanced-reboot $(mkfs_cur_target_dir) '
            '$(if $(filter $*,$(ROOTFS_ID/linksys_homewrk)),homewrk,'
            '$(if $(filter $*,$(foreach model,mx4200v1 mx4200v2 mx4300,$(ROOTFS_ID/linksys_$(model)))),other,unknown))\n')
    return texts


def reviewed_assembly(root, *, resolved=False):
    config_path = root / '.config'
    config = config_path.read_text() if resolved or config_path.exists() else ''
    version = reviewed_version(root, config)
    for symbol, expected in (('USE_APK', 'y'), ('TARGET_ARCH_PACKAGES', f'"{ARCH}"')):
        values = re.findall(rf'^(?:CONFIG_{symbol}=(.*)|# CONFIG_{symbol} is not set)$', config, re.M)
        # The recipe fragment can omit native defaults before defconfig. Reject
        # explicit incompatibility now and require both resolved values at install.
        if values != [expected] and (resolved or values):
            raise ValueError('External APK feeds require APK and ' + ARCH)
    return version, assembly_updates(root, version)


def preflight(root):
    """Read-only caller gate before DTS, mirrors, packages or provenance writes."""
    reviewed_assembly(Path(root).resolve())


def runtime_feeds():
    return ''.join(f'@{tag} {repo["url"]}/packages.adb\n' for tag, repo in REPOSITORIES.items())


def prepare(root):
    root = Path(root).resolve()
    version, updates = reviewed_assembly(root)  # Check all boundaries before writing.
    packages = ' '.join(f'{p}@{tag}' for tag, repo in REPOSITORIES.items() for p in repo['packages'])
    repositories = ' '.join('--repository-config "@' + tag + ' file://$(TOPDIR)/.external-packages/' +
                            tag + '/packages.adb"' for tag in REPOSITORIES)
    for name, text in updates.items():
        put(root, name, text)
    put(root, '.external-packages.mk', 'MX_EXTERNAL_PACKAGES:=' + packages + '\n' +
        'MX_EXTERNAL_REPOSITORIES:=' + repositories + '\n')
    # Runtime entries are editable by LuCI and contain no builder paths.
    overlay = '.external-packages/files' if version == 'SNAPSHOT' else 'files'
    put(root / overlay, RUNTIME_FEEDS, runtime_feeds())


def download(url, path):
    subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20',
                    '--max-time', '180', '--output', str(path), url], check=True)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(root, apk, repositories=None):
    root, apk = Path(root).resolve(), str(Path(apk).resolve())
    repositories = repositories or REPOSITORIES
    version, _ = reviewed_assembly(root, resolved=True)  # Recheck before refreshing provenance.
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
        overlay = '.external-packages/files' if version == 'SNAPSHOT' else 'files'
        for tag in repositories:
            key = destination / 'keys' / (tag + '.pem')
            target = root / overlay / 'etc/apk/keys' / key.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(key, target)
        (destination / 'provenance.json').write_text(json.dumps(record, indent=2) + '\n')


def installed_packages(root):
    installed = {}
    for block in (root / 'lib/apk/db/installed').read_text().split('\n\n'):
        fields = dict(line.split(':', 1) for line in block.splitlines() if ':' in line)
        if 'P' in fields:
            installed[fields['P']] = fields.get('V')
    return installed


def verify_advanced_reboot(root, device):
    root = Path(root)
    installed = installed_packages(root)
    app = 'luci-app-advanced-reboot'
    packages = {app, 'luci-i18n-advanced-reboot-zh-cn'}
    if device == 'homewrk':
        leftovers = sorted(packages & installed.keys())
        leftovers += sorted(str(path.relative_to(root)) for path in root.rglob('*advanced-reboot*'))
        if leftovers:
            raise ValueError('HomeWRK Advanced Reboot residue: ' + ', '.join(leftovers))
        for path in (root / 'usr/share/luci/menu.d').glob('*.json'):
            if any(route == 'admin/system/advanced-reboot' or route.startswith('admin/system/advanced-reboot/')
                   for route in json.loads(path.read_text())):
                raise ValueError('HomeWRK Advanced Reboot menu route: ' + str(path.relative_to(root)))
    elif device == 'other':
        if not all(installed.get(name) for name in packages):
            raise ValueError('Supported model lost Advanced Reboot or its translation')
        for name in (f'usr/share/luci/menu.d/{app}.json', f'usr/share/rpcd/acl.d/{app}.json',
                     'www/luci-static/resources/view/system/advanced-reboot.js',
                     'usr/lib/lua/luci/i18n/advanced-reboot.zh-cn.lmo'):
            path = root / name
            if not path.is_file() or not path.stat().st_size:
                raise ValueError('Supported model lost Advanced Reboot file: ' + name)
    else:
        raise ValueError('Unknown Advanced Reboot device scope: ' + device)


def verify_root(root, provenance):
    root = Path(root)
    record = json.loads(Path(provenance).read_text())
    packages = [(row['repository'], row['name']) for row in record['packages']]
    tags = [row['name'] for row in record['repositories']]
    if (sorted(packages) != sorted((tag, name) for tag, repo in REPOSITORIES.items() for name in repo['packages'])
            or sorted(tags) != sorted(REPOSITORIES)):
        raise ValueError('Incomplete or ambiguous external APK provenance')
    installed = installed_packages(root)
    world = (root / 'etc/apk/world').read_text().splitlines()
    for name in ('luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box'):
        if not installed.get(name):
            raise ValueError('Missing source-built proxy package: ' + name)
    for name in ('etc/config/homeproxy', 'usr/share/luci/menu.d/luci-app-homeproxy.json',
                 'usr/lib/lua/luci/i18n/homeproxy.zh-cn.lmo'):
        if not (root / name).is_file() or not (root / name).stat().st_size:
            raise ValueError('Missing HomeProxy runtime file: ' + name)
    core = root / 'usr/bin/sing-box'
    if core.is_symlink() or not core.is_file() or not core.stat().st_size or not os.access(core, os.X_OK):
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
    feeds = (root / RUNTIME_FEEDS).read_bytes()
    if b'file://' in feeds:
        raise ValueError('Build-only repository leaked into firmware')
    # A malformed earlier line can prevent APK loading later valid entries.
    if feeds != runtime_feeds().encode():
        raise ValueError('Missing runtime repository or noncanonical generated feed')
    for feed in record['repositories']:
        tag = feed['name']
        if digest(root / 'etc/apk/keys' / (tag + '.pem')) != feed['key_sha256']:
            raise ValueError('Missing or wrong runtime signing key: ' + tag)
    return installed


if __name__ == '__main__':
    if sys.argv[1] == 'preflight':
        preflight(sys.argv[2])
    elif sys.argv[1] == 'prepare':
        prepare(sys.argv[2])
    elif sys.argv[1] == 'snapshot':
        snapshot(*sys.argv[2:])
    elif sys.argv[1] == 'verify-root':
        verify_root(*sys.argv[2:])
    elif sys.argv[1] == 'verify-advanced-reboot':
        verify_advanced_reboot(*sys.argv[2:])
    else:
        sys.exit('Unknown external package operation')
