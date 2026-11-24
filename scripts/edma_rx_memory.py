#!/usr/bin/env python3
"""Apply the reviewed qualcommax/ipq807x EDMA RX memory backport before defconfig."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


TARGET = Path('target/linux/qualcommax')
GENERIC = Path('target/linux/generic')
DRIVER = Path('drivers/net/ethernet/qualcomm')
OVERLAY = TARGET / 'files' / DRIVER
NAMES = ('qca_edma.c', 'qca_edma.h')
PATCH_DIR = Path(__file__).resolve().with_name('edma-patches')
EDMA_KBUILD = TARGET / 'patches-6.18/0953-net-ethernet-qca-add-EDMA.patch'
PPE_KBUILD = TARGET / 'patches-6.18/0952-net-ethernet-qca-add-ppe.patch'
BASE_KBUILD = (
    '3e22520e120f49e6764c9b16d01252db8e7521d1ec2c88c6c0817ded629307f3',
    'defe3bbd5f6f5f0e6edbb7e2f1b3e3bc42e58dd5d92b0f65c466738bb18349f0',
)
DONOR_KBUILD = (
    '539a96a3b6a9d014a97cf55edb5ca519fa207d04d5900cb791b038b64f738e0a',
    '8abdac71d929c9325d631beffb684b7405a776abc81e226b9b662e249c859536',
)

# Full, reviewed C + header pairs. Don't infer absorption from a constant,
# one matching hunk, an ancestry claim or a reversed patch that happens to fit.
BASE = (
    '8dfbd80addf50276ef28d5a3d24378a231bece7f0d6d6ec83b8551d0ec656b75',
    '7b644323125da3aa606453c8d66229504a74e7257a95e81d4c3f7171e1ce76fa',
)
BACKPORTED = (
    '6d9f203e1e7737528963854d091a1ba5fbb34a4ca090613e928cc38e5374e800',
    'b2840e8da2d29a0df2672711956019ae291251566674b1c847aae2349d92765c',
)
NATIVE = {
    # OpenWrt PR #26732 at 1698cc246e28cf9f68e5ac4131a20b757728fe49.
    (
        '7adf1b2a699b30b49d790271403d04620d941d61b514bddcf600fb02a6825f02',
        '2c9ce22fbcbce47654cf8b3d96daa217d3b692d77a2d06f0ca99c657c6f6af66',
    ): ('1698cc246e28cf9f68e5ac4131a20b757728fe49', DONOR_KBUILD),
    # The complete PR also retains RX fragment support and its prerequisites.
    (
        '0c51e40ad17595be13c581dfc5bd4be4a4b85e970a36a1b027be024481168a37',
        '589e8aab595b60578e4efee5fa0b375d15ae76ca1acac0f6e93a1f6f02711aa6',
    ): ('71d7a7dbd47d5e0eae1376df78a4a2f3b210b456', DONOR_KBUILD),
}
PATCHES = (
    ('01-rx-buffer-tracking.patch', 'c4252c61fc05b5411c1587b74d899f475693f7b6',
     '1d2173cd8ca12d2370c0438ab847e9304ec758c88399e285bfd90f091da04430'),
    ('02-drop-split-rx.patch', '0f512bbbb48ae436154f66123e722d89053390e5',
     '5698aade8f394aabd3b5faef8518c4a0231bbc017dfb16cdc7ffb0bae3ce5638'),
    ('03-half-page-rx.patch', '1698cc246e28cf9f68e5ac4131a20b757728fe49',
     '2fba4e90ccb34bd8b32596f1436c4b28c0e3845623d0868c611e37d3ec51e20e'),
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read(root, path):
    full = root / path
    if full.resolve() != full or not full.is_file():
        raise ValueError(f'missing or nonregular source file: {path}')
    return full.read_bytes()


def check_source(root):
    versions = re.findall(rb'^KERNEL_PATCHVER[ \t]*:?=[ \t]*([^\s#]+)',
                          read(root, TARGET / 'Makefile'), re.M)
    if versions != [b'6.18']:
        raise ValueError('unreviewed qualcommax kernel layout (expected 6.18)')

    # Use the same config precedence as include/target.mk and
    # include/kernel-defaults.mk, including overrides already on disk.
    subtarget = TARGET / 'ipq807x'
    subconfig = subtarget / 'config-6.18'
    if not (root / subconfig).exists():
        subconfig = subtarget / 'config-default'
    config = {}
    assignment = rb'^(?:# )?(CONFIG_[A-Z0-9_]+)(=.+| is not set)$'
    paths = [GENERIC / 'config-6.18', TARGET / 'config-6.18', subconfig]
    if (root / 'env/kernel-config').exists():
        paths.append(Path('env/kernel-config'))
    for path in paths:
        config.update(re.findall(assignment, read(root, path), re.M))
    if (root / '.config').exists():
        config.update((b'CONFIG_' + name[len(b'CONFIG_KERNEL_'):], value)
                      for name, value in re.findall(assignment, read(root, Path('.config')), re.M)
                      if name.startswith(b'CONFIG_KERNEL_'))
    if config.get(b'CONFIG_QCOM_EDMA') != b'=y':
        raise ValueError('ipq807x no longer selects CONFIG_QCOM_EDMA=y')
    if (config.get(b'CONFIG_ARM64_4K_PAGES') != b'=y' or
            any(config.get(f'CONFIG_ARM64_{size}_PAGES'.encode()) == b'=y'
                for size in ('16K', '64K'))):
        raise ValueError('ipq807x no longer selects 4 KiB pages')
    if config.get(b'CONFIG_MAX_SKB_FRAGS') != b'=17':
        raise ValueError('unreviewed skb_shared_info layout (expected CONFIG_MAX_SKB_FRAGS=17)')
    kbuild = (sha256(read(root, PPE_KBUILD)), sha256(read(root, EDMA_KBUILD)))
    # include/quilt.mk copies these overlays before applying the native layers.
    # A later driver overlay or patch would invalidate the reviewed C/H pair.
    for base in (GENERIC / 'files', GENERIC / 'files-6.18', TARGET / 'files', TARGET / 'files-6.18'):
        for name in (*NAMES, 'Kconfig', 'Makefile'):
            if base == TARGET / 'files' and name in NAMES:
                continue
            path = root / base / DRIVER / name
            if path.exists() or path.is_symlink():
                raise ValueError(f'competing EDMA overlay: {path.relative_to(root)}')
    layers = [GENERIC / f'{name}-6.18' for name in ('backport', 'pending', 'hack')]
    for layer in (*layers, EDMA_KBUILD.parent):
        # Generic directories can fall back to their unsuffixed names.
        directory = root / layer
        if not directory.is_dir():
            directory = root / layer.with_name(layer.name.removesuffix('-6.18'))
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_dir() and not path.is_symlink():
                continue  # native patch-kernel.sh also ignores subdirectories
            if path.suffix != '.patch':
                raise ValueError(f'unreviewed kernel patch layout: {path.relative_to(root)}')
            relative = path.relative_to(root)
            if relative in (PPE_KBUILD, EDMA_KBUILD):
                continue
            data = read(root, relative)
            if re.search(rb'^(?:--- |\+\+\+ |diff |rename (?:from|to) |copy (?:from|to) ).*'
                         rb'(?:/qca_edma\.[ch]|drivers/net/ethernet/qualcomm/(?:Kconfig|Makefile))'
                         rb'(?:\s|"|$)', data, re.M):
                raise ValueError(f'kernel patch touches EDMA: {relative}')
    return kbuild


def apply(root, original):
    # Never patch the actual checkout directly. Validate all predecessors and
    # the complete result before publishing either driver file.
    with tempfile.TemporaryDirectory(prefix='edma-', dir=root / OVERLAY) as directory:
        stage = Path(directory)
        for name, data in zip(NAMES, original):
            out = stage / OVERLAY / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            shutil.copymode(root / OVERLAY / name, out)
        for name, _, expected in PATCHES:
            patch = (PATCH_DIR / name).read_bytes()
            if sha256(patch) != expected:
                raise ValueError(f'EDMA patch digest mismatch: {name}')
            result = subprocess.run(
                ['patch', '-f', '-p1', '--fuzz=0', '--no-backup-if-mismatch'],
                cwd=stage, input=patch, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            if result.returncode:
                raise ValueError(f'{name} failed strict application:\n'
                                 f'{result.stdout.decode(errors="replace")}')
        if tuple(sha256(read(stage, OVERLAY / name)) for name in NAMES) != BACKPORTED:
            raise ValueError('EDMA output differs from the reviewed backport')
        for name in NAMES:
            (stage / OVERLAY / name).replace(root / OVERLAY / name)


def prepare(root):
    kbuild = check_source(root)
    original = (read(root, OVERLAY / NAMES[0]), read(root, OVERLAY / NAMES[1]))
    identity = (sha256(original[0]), sha256(original[1]))
    native = NATIVE.get(identity)
    if native is not None:
        _, wanted_kbuild = native
        if kbuild != wanted_kbuild:
            raise ValueError('unreviewed EDMA Kconfig/Makefile patch for native driver')
        status = 'native'
        output = identity
    elif identity in (BASE, BACKPORTED):
        if kbuild != BASE_KBUILD:
            raise ValueError('unreviewed EDMA Kconfig/Makefile patch for backport')
        status = 'already-applied'
        if identity == BASE:
            apply(root, original)
            status = 'applied'
        output = BACKPORTED
    else:
        raise ValueError(f'unreviewed EDMA driver pair; review upstream drift: {dict(zip(NAMES, identity))}')
    record = {
        'status': status,
        'target': 'qualcommax/ipq807x',
        'driver_overlay': str(OVERLAY),
        'input_driver_sha256': dict(zip(NAMES, identity)),
        'driver_sha256': dict(zip(NAMES, output)),
        'kbuild_sha256': dict(zip((PPE_KBUILD.name, EDMA_KBUILD.name), kbuild)),
        'patches': [] if status == 'native' else [
            {'file': name, 'commit': commit, 'sha256': digest} for name, commit, digest in PATCHES
        ],
    }
    if native is not None:
        record['native_reference'] = native[0]
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root', type=Path, help='unconfigured ImmortalWrt Snapshot source tree')
    args = parser.parse_args()
    try:
        record = prepare(args.source_root.resolve())
    except (OSError, ValueError) as exc:
        parser.exit(1, f'EDMA RX backport: {exc}\n')
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
