#!/usr/bin/env python3
"""Verify the built HomeWRK FIT contains a complete, usable LuCI RAM root."""
import argparse
import ctypes
import ctypes.util
import gzip
import hashlib
import io
import json
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


def verify(path, record=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= LIMIT:
        raise ValueError('invalid HomeWRK initramfs file')
    data = path.read_bytes()
    result: dict = verify_files(ram_files(kernel_data(data)))
    result.update(name=path.name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
    if record:
        Path(record).write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--record', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.image, args.record)))
