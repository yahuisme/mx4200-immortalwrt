#!/usr/bin/env python3
"""Validate required post-defconfig selections or collect exactly four images."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check_config(tree):
    selected = set((tree / '.config').read_text().splitlines())
    contract = {line for line in (ROOT / 'Config/MX4200.txt').read_text().splitlines()
                if line.startswith('CONFIG_')}
    wanted = {line for line in contract if line.endswith('=y')}
    disabled = {line[:-2] for line in contract if line.endswith('=n')}
    forbidden = sorted(line for line in selected
                       if line.endswith(('=y', '=m')) and line[:-2] in disabled)

    missing = sorted(wanted - selected)
    devices = sorted(x for x in selected if re.fullmatch(r'CONFIG_TARGET_DEVICE_.*=y', x))
    expected = [f'CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v{v}=y' for v in (1, 2)]
    if missing or forbidden or devices != expected:
        raise ValueError(f'Configuration contract failed: missing={missing}, forbidden={forbidden}, devices={devices}')
    print(f'PASS: {len(wanted)} required selections and exactly MX4200v1/v2')


def tool(tree, name):
    local = tree / 'staging_dir/host/bin' / name
    found = str(local) if local.is_file() else shutil.which(name)
    if not found:
        raise ValueError(f'Required image validation tool missing: {name}')
    return found


def run_tool(command, **kwargs):
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        raise ValueError(f'Image validation failed ({command[0]}): {result.stderr!r}')
    return result.stdout


def sysupgrade(tree, path, version):
    # fwtool validates the whole-image CRC before returning metadata.
    metadata = json.loads(run_tool([tool(tree, 'fwtool'), '-i', '-', str(path)]))
    board = f'linksys_mx4200v{version}'
    if (not isinstance(metadata, dict)
            or metadata.get('supported_devices') != [board.replace('_', ',', 1)]
            or not isinstance(metadata.get('version'), dict)
            or metadata['version'].get('board') != board
            or metadata['version'].get('target') != 'qualcommax/ipq807x'):
        raise ValueError(f'Wrong MX4200v{version} sysupgrade metadata: {path}')
    prefix = 'sysupgrade-' + board
    try:
        with tarfile.open(path, 'r:') as archive:
            members = archive.getmembers()
            expected = {prefix, *(prefix + '/' + n for n in ('CONTROL', 'kernel', 'root'))}
            if (len(members) != 4 or {m.name for m in members} != expected
                    or any(not (m.isdir() if m.name == prefix else m.isfile() and m.size > 0)
                           for m in members)):
                raise ValueError(f'Invalid sysupgrade tar structure: {path}')
            kernel_file = archive.extractfile(prefix + '/kernel')
            root_file = archive.extractfile(prefix + '/root')
            assert kernel_file is not None and root_file is not None
            kernel, root = kernel_file.read(), root_file.read()
            if kernel[:4] != b'\xd0\x0d\xfe\xed' or root[:4] != b'hsqs':
                raise ValueError(f'Expected FIT kernel and SquashFS root: {path}')
            return kernel, root
    except tarfile.TarError as exc:
        raise ValueError(f'Invalid sysupgrade tar: {path}') from exc


def factory(tree, path, kernel, root):
    # Mirrors qualcommax's append-kernel | pad-to 6144k | append-ubi |
    # linksys-image (include/image-commands.mk); no private UBI parser.
    data = path.read_bytes()
    kernel_size, block_size, page_size = 6144 * 1024, 128 * 1024, 2048
    if (len(data) <= kernel_size + 2 * block_size or len(data) % page_size
            or data[:len(kernel)] != kernel
            or data[len(kernel):kernel_size] != b'\0' * (kernel_size - len(kernel))):
        raise ValueError(f'Invalid factory kernel/layout: {path}')
    checksum = int(run_tool([tool(tree, 'cksum')], input=data[:-256]).split()[0])
    trailer = (f'.LINKSYS.01000409{"MX4200":<15}{checksum:08X}{"0":<8}'
               f'{"K0000000F0246434":<16}').encode() + bytes(192)
    if data[-256:] != trailer:
        raise ValueError(f'Invalid factory Linksys trailer/checksum: {path}')
    ubi_end = len(data) - page_size
    if ((ubi_end - kernel_size) % block_size
            or data[ubi_end:-256] != b'\xff' * (page_size - 256)
            or any(data[n:n+4] != b'UBI#' for n in range(kernel_size, ubi_end, block_size))):
        raise ValueError(f'Invalid factory UBI layout: {path}')
    with tempfile.TemporaryDirectory() as directory:
        run_tool([tool(tree, 'ubireader_extract_images'), '-s', str(kernel_size),
                  '-n', str(ubi_end), '-p', str(block_size), '-o', directory, str(path)])
        volumes = list(Path(directory).rglob('*_vol-rootfs.ubifs'))
        if len(volumes) != 1:
            raise ValueError(f'Expected one factory rootfs volume: {path}')
        extracted = volumes[0].read_bytes()
        # SquashFS bytes_used excludes format-dependent 0/FF padding.
        used = int.from_bytes(root[40:48], 'little')
        if (not 96 <= used <= len(root) or extracted[:used] != root[:used]
                or root[used:] != bytes(len(root) - used)
                or extracted[used:] != b'\xff' * (len(extracted) - used)):
            raise ValueError(f'Factory/sysupgrade rootfs mismatch: {path}')


def images(tree):
    source = tree / 'bin/targets/qualcommax/ipq807x'
    files = []
    for version in (1, 2):
        for kind in ('factory', 'sysupgrade'):
            matches = list(source.glob(f'*-linksys_mx4200v{version}-squashfs-{kind}.bin'))
            if len(matches) != 1 or matches[0].stat().st_size == 0:
                raise ValueError(f'Expected one nonempty MX4200v{version} {kind} image: {matches}')
            files.extend(matches)
    for version in (1, 2):
        kernel, root = sysupgrade(tree, files[version * 2 - 1], version)
        factory(tree, files[version * 2 - 2], kernel, root)
    output = tree / 'upload'
    if output.exists() and any(output.iterdir()):
        raise ValueError('Upload directory must be empty')
    output.mkdir(exist_ok=True)
    for path in files:
        shutil.copy2(path, output / path.name)
    print('PASS: exactly four images staged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('config', 'images'))
    parser.add_argument('tree', type=Path)
    args = parser.parse_args()
    (check_config if args.mode == 'config' else images)(args.tree)
