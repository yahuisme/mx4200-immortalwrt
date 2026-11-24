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
from pathlib import Path
import stat
import struct
import zlib

LIMIT = 256 * 1024 * 1024
REQUIRED = ('www/cgi-bin/luci', 'www/luci-static/resources/view/system/flash.js',
            'usr/share/luci/menu.d/luci-mod-system.json', 'usr/sbin/uhttpd',
            'etc/init.d/uhttpd', 'etc/rc.d/S50uhttpd')
PACKAGES = {'luci', 'luci-mod-system', 'luci-i18n-base-zh-cn', 'uhttpd', 'rpcd'}
HOMEWRK_CONFIG = 'config@oak03'


def fdt_nodes(blob):
    """Read named nodes and properties from the FIT or its embedded DTB."""
    if len(blob) < 40:
        raise ValueError('truncated FDT')
    magic, total, off_struct, off_strings, _, version, _, _, size_strings, size_struct = struct.unpack_from('>10I', blob)
    if (magic != 0xd00dfeed or not 40 <= total <= len(blob) or version != 17
            or min(off_struct, off_strings) < 40 or off_struct % 4 or size_struct % 4
            or not (off_struct + size_struct <= off_strings or off_strings + size_strings <= off_struct)
            or off_struct + size_struct > total or off_strings + size_strings > total):
        raise ValueError('invalid FDT bounds')
    strings = blob[off_strings:off_strings + size_strings]
    tree = blob[off_struct:off_struct + size_struct]
    nodes, stack, index, ended = {}, [], 0, False
    while index + 4 <= len(tree):
        token = struct.unpack_from('>I', tree, index)[0]
        index += 4
        if token == 1:
            end = tree.index(b'\0', index)
            name = tree[index:end].decode()
            if (bool(name) != bool(stack)) or '/' in name:
                raise ValueError('invalid FDT node name')
            stack.append(name)
            path = '/'.join(stack) or '/'
            if path in nodes:
                raise ValueError('duplicate FDT node')
            nodes[path] = {}
            index = (end + 4) & ~3
        elif token == 2:
            if not stack:
                raise ValueError('invalid FIT node stack')
            stack.pop()
        elif token == 3:
            if index + 8 > len(tree):
                raise ValueError('truncated FDT property')
            length, offset = struct.unpack_from('>II', tree, index)
            index += 8
            if not stack or index + length > len(tree) or offset >= len(strings):
                raise ValueError('invalid FIT property bounds')
            end = strings.index(b'\0', offset)
            name = strings[offset:end].decode()
            props = nodes['/'.join(stack) or '/']
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
    if not ended or stack or '/' not in nodes or index != len(tree):
        raise ValueError('incomplete FDT structure')
    return nodes


def kernel_data(fit):
    """Validate the native HomeWRK boot configuration before reading its kernel."""
    nodes = fdt_nodes(fit)
    config = nodes.get('/configurations/' + HOMEWRK_CONFIG)
    if (nodes.get('/configurations', {}).get('default') != HOMEWRK_CONFIG.encode() + b'\0'
            or config is None or not set(config) <= {'description', 'compatible', 'kernel', 'fdt'}):
        raise ValueError('invalid HomeWRK FIT default boot configuration')

    def component(role, kind, compression):
        ref = config.get(role, b'')
        if not re.fullmatch(rb'[A-Za-z0-9_.@-]+\x00', ref):
            raise ValueError(f'invalid FIT {role} image reference')
        path = '/images/' + ref[:-1].decode('ascii')
        image = nodes.get(path)
        if image is None:
            raise ValueError(f'missing FIT {role} image reference')
        data = image.get('data')
        if (not data or image.get('type') != kind or image.get('compression') != compression
                or image.get('arch') != b'arm64\0'):
            raise ValueError(f'invalid FIT {role} component')
        hashes = [props for name, props in nodes.items()
                  if name.startswith(path + '/hash') and name.count('/') == 3]
        expected = {b'crc32\0': struct.pack('>I', zlib.crc32(data)),
                    b'sha1\0': hashlib.sha1(data, usedforsecurity=False).digest()}
        if len(hashes) != len(expected) or {entry.get('algo') for entry in hashes} != set(expected):
            raise ValueError(f'invalid FIT {role} hash inventory')
        for entry in hashes:
            algo = entry['algo']
            if entry.get('value') != expected[algo] or 'ignore' in entry:
                raise ValueError(f'FIT {role} {algo[:-1].decode()} hash mismatch')
        return data

    kernel = component('kernel', b'kernel\0', b'gzip\0')
    dtb = component('fdt', b'flat_dt\0', b'none\0')
    try:
        compatible = fdt_nodes(dtb)['/'].get('compatible', b'').split(b'\0')
    except ValueError as error:
        raise ValueError('invalid HomeWRK device tree') from error
    if compatible[0] != b'linksys,homewrk' or compatible[-1] != b'':
        raise ValueError('FIT does not contain a HomeWRK device tree')
    with gzip.GzipFile(fileobj=io.BytesIO(kernel)) as stream:
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


def verify(path, record=None, source=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= LIMIT:
        raise ValueError('invalid HomeWRK initramfs file')
    data = path.read_bytes()
    files = ram_files(kernel_data(data))
    result: dict = verify_files(files)
    if source is not None:
        config = json.loads(Path(source).read_text())
        result.update(verify_chinese(files))
        for name in ('init', 'sbin/sysupgrade', 'lib/upgrade/platform.sh'):
            mode, payload = files.get(name, (0, b''))
            if not stat.S_ISREG(mode) or not payload:
                raise ValueError('missing HomeWRK RAM-system upgrade file: ' + name)
        release = files.get('etc/openwrt_release', (0, b''))[1].decode()
        if (re.findall(r"(?m)^DISTRIB_RELEASE='([^']+)'$", release) != ['SNAPSHOT'] or
                re.findall(r"(?m)^DISTRIB_REVISION='([^']+)'$", release) != [config['revision']]):
            raise ValueError('HomeWRK RAM-system release/revision differs from build source')
        installed = files['lib/apk/db/installed'][1].decode()
        if re.search(r'(?m)^P:(?:sing-box|luci-\S*(?:homeproxy|aurora)|luci-app-advanced-reboot)$', installed) or any(
                name.startswith('etc/uci-defaults/99-mx4200-') for name in files):
            raise ValueError('Formal customization in HomeWRK RAM system')
        result.update(source_sha=config['source_sha'], revision=config['revision'])
    result.update(name=path.name, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                  fit_config=HOMEWRK_CONFIG)
    if record:
        Path(record).write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--source-record', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.image, args.record, args.source_record)))
