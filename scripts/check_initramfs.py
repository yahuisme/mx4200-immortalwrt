#!/usr/bin/env python3
"""Verify the built HomeWRK FIT contains a complete, usable LuCI RAM root."""
import argparse
import ctypes
import ctypes.util
import gzip
import hashlib
import io
import json
import re
import shlex
import subprocess
from pathlib import Path
import stat
import struct

LIMIT = 256 * 1024 * 1024
REQUIRED = ('www/cgi-bin/luci', 'www/luci-static/resources/view/system/flash.js',
            'usr/share/luci/menu.d/luci-mod-system.json', 'usr/sbin/uhttpd',
            'etc/init.d/uhttpd', 'etc/rc.d/S50uhttpd')
PACKAGES = {'luci-mod-system', 'uhttpd', 'rpcd'}


def kernel_data(fit):
    """Read inline kernel data from the native flattened-device-tree FIT."""
    if len(fit) < 40:
        raise ValueError('truncated FIT')
    magic, total, off_struct, off_strings, _, _, _, _, size_strings, size_struct = struct.unpack('>10I', fit[:40])
    if (magic != 0xd00dfeed or total > len(fit) or total < 40
            or off_struct + size_struct > total or off_strings + size_strings > total):
        raise ValueError('invalid FIT bounds')
    strings = fit[off_strings:off_strings + size_strings]
    tree = fit[off_struct:off_struct + size_struct]
    nodes, stack, index, ended = {}, [], 0, False
    while index + 4 <= len(tree):
        token = struct.unpack_from('>I', tree, index)[0]
        index += 4
        if token == 1:
            end = tree.index(b'\0', index)
            stack.append(tree[index:end].decode())
            index = (end + 4) & ~3
        elif token == 2:
            if not stack:
                raise ValueError('invalid FIT node stack')
            stack.pop()
        elif token == 3:
            length, offset = struct.unpack_from('>II', tree, index)
            index += 8
            if not stack or index + length > len(tree) or offset >= len(strings):
                raise ValueError('invalid FIT property bounds')
            end = strings.index(b'\0', offset)
            name = strings[offset:end].decode()
            path = '/'.join(stack)
            props = nodes.setdefault(path, {})
            if name in props:
                raise ValueError('duplicate FIT property')
            props[name] = tree[index:index + length]
            index = (index + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            ended = True
            break
        else:
            raise ValueError('invalid FIT token')
    kernels = [v for k, v in nodes.items() if k.startswith('/images/')
               and k.count('/') == 2 and v.get('type') == b'kernel\0']
    if not ended or stack or len(kernels) != 1 or kernels[0].get('compression') != b'gzip\0':
        raise ValueError('expected one gzip FIT kernel')
    with gzip.GzipFile(fileobj=io.BytesIO(kernels[0]['data'])) as stream:
        kernel = stream.read(LIMIT + 1)
    if len(kernel) > LIMIT:
        raise ValueError('kernel exceeds inspection bound')
    return kernel


def cpio_files(data):
    """Require complete newc framing before trusting any pathname or file."""
    files, index = {}, 0
    while index + 110 <= len(data):
        header = data[index:index + 110]
        if header[:6] != b'070701':
            raise ValueError('invalid CPIO header')
        values = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        mode, size, length = values[1], values[6], values[11]
        start = index + 110
        if length < 1 or start + length > len(data) or data[start + length - 1] != 0:
            raise ValueError('invalid CPIO pathname')
        name = data[start:start + length - 1].decode()
        start = (start + length + 3) & ~3
        end = start + size
        if end > len(data):
            raise ValueError('truncated CPIO data')
        index = (end + 3) & ~3
        if name == 'TRAILER!!!':
            if size or any(data[index:]):
                raise ValueError('invalid CPIO trailer')
            return files
        name = name.removeprefix('./')
        if name.startswith('/') or '..' in Path(name).parts or name in files:
            raise ValueError('unsafe or duplicate CPIO pathname')
        files[name] = (mode, data[start:end])
    raise ValueError('missing CPIO trailer')


def ram_files(kernel):
    library = ctypes.util.find_library('zstd')
    if not library:
        raise ValueError('libzstd is required')
    zstd = ctypes.CDLL(library)
    zstd.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    zstd.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t
    zstd.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    zstd.ZSTD_decompress.restype = ctypes.c_size_t
    zstd.ZSTD_isError.argtypes = [ctypes.c_size_t]
    zstd.ZSTD_isError.restype = ctypes.c_uint
    index = 0
    while (index := kernel.find(b'\x28\xb5\x2f\xfd', index)) >= 0:
        source = ctypes.create_string_buffer(kernel[index:])
        length = zstd.ZSTD_findFrameCompressedSize(source, len(kernel) - index)
        index += 4
        if zstd.ZSTD_isError(length):
            continue
        destination = ctypes.create_string_buffer(LIMIT)
        size = zstd.ZSTD_decompress(destination, LIMIT, source, length)
        if not zstd.ZSTD_isError(size) and destination[:6] == b'070701':
            return cpio_files(destination[:size])
    raise ValueError('no complete Zstandard CPIO initramfs')


def verify_files(files):
    for name in REQUIRED:
        if name not in files:
            raise ValueError('missing LuCI RAM-system file: ' + name)
        mode, data = files[name]
        expected_type = stat.S_ISLNK if name == 'etc/rc.d/S50uhttpd' else stat.S_ISREG
        if not data or not expected_type(mode):
            raise ValueError('invalid LuCI RAM-system file: ' + name)
    for name in ('www/cgi-bin/luci', 'usr/sbin/uhttpd', 'etc/init.d/uhttpd'):
        if not files[name][0] & 0o111:
            raise ValueError('non-executable RAM-system program: ' + name)
    if files['etc/rc.d/S50uhttpd'][1] not in (b'../init.d/uhttpd', b'../init.d/uhttpd\0'):
        raise ValueError('uhttpd startup link differs')
    installed = files.get('lib/apk/db/installed', (0, b''))[1].decode()
    packages = {line[2:] for line in installed.splitlines() if line.startswith('P:')}
    if not PACKAGES <= packages:
        raise ValueError('missing LuCI RAM-system packages: ' + ', '.join(sorted(PACKAGES - packages)))
    return dict(paths=list(REQUIRED), packages=sorted(PACKAGES), complete_cpio=True)


def uci_rows(data):
    """Tokenize UCI without executing firmware shell or changing host UCI."""
    return [row for line in data.decode().splitlines()
            if (row := shlex.split(line, comments=True))]


def verify_chinese(files):
    # Official luci.mk maps zh_Hans -> zh-cn; system strings share base.po.
    dictionary = 'usr/lib/lua/luci/i18n/base.zh-cn.lmo'
    for name in (dictionary, 'etc/config/luci'):
        mode, data = files.get(name, (0, b''))
        if not stat.S_ISREG(mode) or not data:
            raise ValueError('missing Chinese LuCI file: ' + name)
    data = files[dictionary][1]
    if len(data) < 20:
        raise ValueError('invalid Chinese dictionary framing')
    offset = struct.unpack('>I', data[-4:])[0]
    if offset >= len(data) - 4 or (len(data) - 4 - offset) % 16:
        raise ValueError('invalid Chinese dictionary index')
    keys, translated = [], False
    for index in range(offset, len(data) - 4, 16):
        key, _, start, length = struct.unpack_from('>4I', data, index)
        if not length or start + length > offset:
            raise ValueError('invalid Chinese dictionary translation bounds')
        try:
            value = data[start:start + length].decode()
        except UnicodeDecodeError as exc:
            raise ValueError('invalid Chinese dictionary encoding') from exc
        translated |= any('\u4e00' <= ch <= '\u9fff' for ch in value)
        keys.append(key)
    if keys != sorted(set(keys)) or not translated:
        raise ValueError('invalid Chinese dictionary translations')
    section, languages = None, []
    for row in uci_rows(files['etc/config/luci'][1]):
        if row[0] == 'config':
            section = row[1:]
        elif section == ['core', 'main'] and row[:2] == ['option', 'lang']:
            languages.append(row[2:])
    if languages != [['auto']]:
        raise ValueError('LuCI must retain official default language auto')
    registration = "uci set luci.languages.zh_cn='简体中文 (Simplified Chinese)'; uci commit luci\n".encode()
    mode, data = files.get('etc/uci-defaults/luci-i18n-base-zh-cn', (0, b''))
    if not stat.S_ISREG(mode) or data != registration:
        raise ValueError('missing official Chinese LuCI language registration')
    return dict(language='zh_cn', default_language='auto', dictionaries=[dictionary])


def git(source, *args):
    try:
        return subprocess.run(['git', '-C', str(source), *args], check=True,
                              capture_output=True).stdout
    except subprocess.CalledProcessError as exc:
        raise ValueError('unavailable official Git objects: ' + str(source)) from exc


def official_tree(source, repository):
    """Use committed blobs, not the potentially customized build worktree."""
    source = Path(source)
    if not (source / '.git').exists():
        raise ValueError('official source must have its own Git metadata')
    origin = git(source, 'remote', 'get-url', 'origin').decode().strip()
    if origin not in (f'https://github.com/immortalwrt/{repository}.git',
                      f'https://github.com/immortalwrt/{repository}'):
        raise ValueError('not an official ImmortalWrt source origin')
    sha = git(source, 'rev-parse', '--verify', 'HEAD').decode().strip()
    # One batch process, also works with detached HEAD and .git worktree files.
    entries = git(source, 'ls-tree', '-rz', sha).split(b'\0')
    tree = {}
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, kind, oid = metadata.split()
        if kind == b'blob':
            tree[name.decode()] = (int(mode, 8), oid.decode())
    wanted = [name for name in tree if name.endswith(('/Makefile', '/luci', '/mac80211.uc', '/config_generate', '/base.po'))
              or name == 'luci.mk' or '/files/' in name or '/root/' in name]
    # One bounded batch replaces thousands of subprocesses; skip binary source
    # and read only recipe/default inputs used below.
    stream = io.BytesIO(subprocess.run(['git', '-C', str(source), 'cat-file', '--batch'],
        input=''.join(tree[name][1] + '\n' for name in wanted).encode(),
        capture_output=True, check=True).stdout)
    for name in wanted:
        header = stream.readline().split()
        if len(header) != 3 or header[1] != b'blob':
            raise ValueError('invalid official Git blob response')
        data = stream.read(int(header[2])); stream.read(1)
        tree[name] = (*tree[name], data)
    return sha, tree


def blob(source, tree, name):
    if name not in tree:
        raise ValueError('missing official source input: ' + name)
    if len(tree[name]) == 3:
        return tree[name][2]
    return git(source, 'cat-file', 'blob', tree[name][1])


def installed_records(files):
    mode, raw = files.get('lib/apk/db/installed', (0, b''))
    if not stat.S_ISREG(mode) or not raw:
        raise ValueError('missing regular installed APK database')
    records = {}
    for block in raw.decode().split('\n\n'):
        row = dict(line.split(':', 1) for line in block.splitlines() if ':' in line and len(line.split(':', 1)[0]) == 1)
        if 'P' not in row:
            continue
        if row['P'] in records:
            raise ValueError('duplicate installed APK package')
        records[row['P']] = row
    return records


def official_packages(files, source):
    """Native target metadata roots plus dependencies of the installed APKs.

    The isolated configuration/source guard owns solver provenance; this gate
    rejects disconnected extra applications, rather than maintaining a blacklist.
    """
    lines = (Path(source) / 'tmp/.targetinfo').read_text().splitlines()
    target = profile = None
    roots = set()
    for line in lines:
        key, _, value = line.partition(': ')
        if key == 'Target': target, profile = value, None
        elif key == 'Target-Profile': profile = value
        elif target == 'qualcommax/ipq807x' and key == 'Default-Packages': roots.update(value.split())
        elif target == 'qualcommax/ipq807x' and profile == 'DEVICE_linksys_homewrk' and key == 'Target-Profile-Packages': roots.update(value.split())
    if not roots:
        raise ValueError('missing native HomeWRK package metadata')
    removed = {name[1:] for name in roots if name.startswith('-')}
    roots = {name for name in roots if not name.startswith('-')} - removed
    records = installed_records(files)
    roots |= {'kernel', 'luci', 'luci-i18n-base-zh-cn'}
    providers = {}
    for name, record in records.items():
        providers[name] = name
        for alias in record.get('p', '').split():
            providers[re.split(r'[<>=~]', alias)[0]] = name
    pending, allowed = list(roots), set()
    while pending:
        name = providers.get(pending.pop())
        if not name or name in allowed:
            continue
        allowed.add(name)
        for dependency in records[name].get('D', '').split():
            if not dependency.startswith('!'):
                pending.append(re.split(r'[<>=~]', dependency)[0])
        # Official selected language generates translations for every selected
        # package that has po/zh_Hans, not only the luci collection itself.
        if name.startswith('luci-'):
            suffix = re.sub(r'^luci-(?:app|mod|theme|proto)-', '', name)
            pending.append('luci-i18n-' + suffix + '-zh-cn')
    extra = set(records) - allowed
    if extra:
        raise ValueError('unexpected RAM-system packages: ' + ', '.join(sorted(extra)))
    return sorted(allowed)


def verify_official(files, source):
    source = Path(source)
    sha, tree = official_tree(source, 'immortalwrt')
    luci = source / 'feeds/luci'
    luci_sha, luci_tree = official_tree(luci, 'luci')
    packages = official_packages(files, source)
    chinese = verify_chinese(files)
    luci_mk = blob(luci, luci_tree, 'luci.mk')
    if b'LUCI_LC_ALIAS.zh_Hans=zh-cn' not in luci_mk:
        raise ValueError('official Chinese locale alias changed; review required')
    po = blob(luci, luci_tree, 'modules/luci-base/po/zh_Hans/base.po')
    if not re.search(rb'msgstr "[^"\n]*[\x80-\xff]', po):
        raise ValueError('official Chinese base/system catalog missing translations')
    defaults = {}

    def compare(name, expected, semantic=False):
        mode, actual = files.get(name, (0, b''))
        if not stat.S_ISREG(mode) or (uci_rows(actual) != uci_rows(expected) if semantic else actual != expected):
            raise ValueError('official default missing or changed: ' + name)
        defaults[name] = hashlib.sha256(actual).hexdigest()

    # Effective base-files layering, requiring original files rather than only
    # inspecting whichever happen to survive in the image.
    effective = {}
    for prefix in ('package/base-files/files/', 'target/linux/generic/base-files/',
                   'target/linux/qualcommax/base-files/', 'target/linux/qualcommax/ipq807x/base-files/'):
        for name in tree:
            if name.startswith(prefix):
                destination = name[len(prefix):]
                if destination in ('bin/config_generate',) or destination.startswith(('etc/board.d/', 'etc/uci-defaults/')):
                    effective[destination] = name
    # Native APK install intentionally deletes this migration (base-files recipe).
    base_recipe = blob(source, tree, 'package/base-files/Makefile') if 'package/base-files/Makefile' in tree else b''
    if b'rm -f $(1)/etc/uci-defaults/13_fix-group-user' in base_recipe:
        effective.pop('etc/uci-defaults/13_fix-group-user', None)
    for name, original in effective.items(): compare(name, blob(source, tree, original))
    wireless = 'package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc'
    compare('lib/wifi/mac80211.uc', blob(source, tree, wireless))
    original_luci = blob(luci, luci_tree, 'modules/luci-base/root/etc/config/luci')
    compare('etc/config/luci', original_luci, semantic=True)

    for name in luci_tree:
        marker = '/root/usr/share/luci/menu.d/'
        if marker in name:
            package = name.split('/')[1]
            if package in packages:
                compare('usr/share/luci/menu.d/' + name.split(marker, 1)[1], blob(luci, luci_tree, name))
    # Content allowlist for every installed defaults/menu file. Path matching is
    # mandatory: renaming an official-looking file must not conceal an overlay.
    candidates = {}
    inventories = [(source, tree), (luci, luci_tree)]
    packages_feed = source / 'feeds/packages'
    if (packages_feed / '.git').exists():
        _, package_tree = official_tree(packages_feed, 'packages')
        inventories.append((packages_feed, package_tree))
    for base, inventory in inventories:
        for name in inventory:
            for marker in ('etc/uci-defaults/', 'usr/share/luci/menu.d/'):
                if marker in name:
                    destination = marker + name.split(marker, 1)[1]
                    candidates.setdefault(destination, []).append(blob(base, inventory, name))
            if name.endswith('/Makefile'):
                recipe = blob(base, inventory, name).decode()
                # Resolve native renamed INSTALL_* inputs from committed recipes.
                # Never use package output or an image's APK checksums as source.
                for match in re.finditer(r'\$\((?:INSTALL_DATA|INSTALL_BIN|INSTALL_CONF)\)\s+((?:\./|\$\(CURDIR\)/)[^\s]+)\s+\$\(1\)/(etc/uci-defaults(?:/[^\s,]*)?)', recipe):
                    original, destination = match.groups()
                    original = original.replace('$(CURDIR)/', '').removeprefix('./')
                    original = str(Path(name).parent / original)
                    if original in inventory:
                        if destination == 'etc/uci-defaults' or destination.endswith('/'):
                            destination = destination.rstrip('/') + '/' + Path(original).name
                        candidates.setdefault(destination, []).append(blob(base, inventory, original))
        if base == source:
            # uboot-envtools uses a native wildcard choice in its make recipe.
            original = 'package/boot/uboot-tools/uboot-envtools/files/qualcommax_ipq807x'
            if original in inventory:
                candidates.setdefault('etc/uci-defaults/30_uboot-envtools', []).append(blob(base, inventory, original))
    for name, (mode, data) in files.items():
        if name.startswith(('etc/uci-defaults/', 'usr/share/luci/menu.d/')) and not stat.S_ISDIR(mode):
            expected = candidates.get(name, [])
            if name.startswith('etc/uci-defaults/luci-i18n-'):
                package = name.rsplit('/', 1)[1]
                if package in packages and package.endswith('-zh-cn'):
                    expected.append("uci set luci.languages.zh_cn='简体中文 (Simplified Chinese)'; uci commit luci\n".encode())
            if not stat.S_ISREG(mode) or data not in expected:
                raise ValueError('unrecognized or modified official defaults/menu: ' + name)
    # An orphan program/config/theme is not made official by a harmless name.
    # Package identity closure above plus native APK ownership catches leftovers
    # without banning names that upstream itself might legitimately introduce.
    owned = set()
    directory = ''
    for line in files['lib/apk/db/installed'][1].decode().splitlines():
        if line.startswith('F:'):
            directory = line[2:]
        elif line.startswith('R:'):
            owned.add((directory + '/' + line[2:]).lstrip('/'))
    for name, (mode, _) in files.items():
        if (not stat.S_ISDIR(mode) and name.startswith(('etc/config/', 'usr/bin/', 'usr/sbin/', 'www/luci-static/'))
                and name not in owned):
            raise ValueError('unowned RAM-system config/program/theme: ' + name)
    return dict(**chinese, official_source=sha, official_luci=luci_sha,
                official_defaults=defaults, installed_packages=packages)


def verify(path, record=None, source=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= LIMIT:
        raise ValueError('invalid HomeWRK initramfs file')
    data = path.read_bytes()
    files = ram_files(kernel_data(data))
    result: dict = verify_files(files)
    if source is not None:
        result.update(verify_official(files, source))
    result.update(name=path.name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    if record:
        Path(record).write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--record', type=Path)
    parser.add_argument('--source', type=Path, required=True,
                        help='pristine official build tree, including feed Git objects and native tmp/.targetinfo')
    args = parser.parse_args()
    print(json.dumps(verify(args.image, args.record, args.source)))
