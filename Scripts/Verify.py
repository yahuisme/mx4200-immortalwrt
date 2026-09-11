#!/usr/bin/env python3
"""Validate required post-defconfig selections or collect exactly four images."""
import argparse
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def check_config(tree):
    selected = set((tree / '.config').read_text().splitlines())
    wanted = {line for p in (ROOT / 'Config').glob('*.txt') for line in p.read_text().splitlines()
              if line.startswith('CONFIG_') and line.endswith('=y')}
    # OpenWrt makes VERSIONOPT invisible when release defaults already provide identity.
    wanted.discard('CONFIG_VERSIONOPT=y')

    missing = sorted(wanted - selected)
    devices = sorted(x for x in selected if re.fullmatch(r'CONFIG_TARGET_DEVICE_.*=y', x))
    expected = [f'CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v{v}=y' for v in (1, 2)]
    if missing or devices != expected:
        raise ValueError(f'Configuration contract failed: missing={missing}, devices={devices}')
    print(f'PASS: {len(wanted)} required selections and exactly MX4200v1/v2')


def images(tree):
    source = tree / 'bin/targets/qualcommax/ipq807x'
    files = []
    for version in (1, 2):
        for kind in ('factory', 'sysupgrade'):
            matches = list(source.glob(f'*-linksys_mx4200v{version}-squashfs-{kind}.bin'))
            if len(matches) != 1 or matches[0].stat().st_size == 0:
                raise ValueError(f'Expected one nonempty MX4200v{version} {kind} image: {matches}')
            files.extend(matches)
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
