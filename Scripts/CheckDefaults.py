#!/usr/bin/env python3
"""Reject unavailable per-device default packages after make defconfig."""
from pathlib import Path
import re
import sys


def check(config, packageinfo):
    values = dict(re.findall(r'^CONFIG_([^=]+)=(.*)$', config, re.M))
    defaults = sorted(key.removeprefix('MODULE_DEFAULT_') for key, value in values.items()
                      if key.startswith('MODULE_DEFAULT_') and value == 'y')
    if not defaults:
        raise ValueError('no enabled MODULE_DEFAULT packages; expected per-device defconfig')
    available = {key.removeprefix('PACKAGE_') for key, value in values.items()
                 if key.startswith('PACKAGE_') and value in ('y', 'm')}
    # Virtual defaults (e.g. nftables) are satisfied by selected providers.
    for block in re.split(r'^Package: ', packageinfo, flags=re.M)[1:]:
        package = block.splitlines()[0]
        provides = re.search(r'^Provides: (.*)$', block, re.M)
        if package in available and provides:
            available.update(provides.group(1).split())
    missing = [package for package in defaults if package not in available]
    if missing:
        raise ValueError('unavailable device default packages: ' + ', '.join(missing))
    return defaults


if __name__ == '__main__':
    try:
        defaults = check(Path(sys.argv[1]).read_text(), Path(sys.argv[2]).read_text())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    print(f'Verified {len(defaults)} device default packages are selected (y/m)')
