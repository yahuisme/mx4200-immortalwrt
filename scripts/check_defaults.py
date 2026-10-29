#!/usr/bin/env python3
"""Reject unavailable device defaults and lost explicit requests after defconfig."""
from pathlib import Path
import re
import sys


FORBIDDEN_PACKAGES = ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn',
                      'luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box')


def check(config, packageinfo, requested=""):
    values = dict(re.findall(r'^CONFIG_([^=]+)=(.*)$', config, re.M))
    forbidden = [package for package in FORBIDDEN_PACKAGES
                 if values.get('PACKAGE_' + package) in ('y', 'm')]
    if forbidden:
        raise ValueError('forbidden packages selected: ' + ', '.join(forbidden))
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
    selections = dict(re.findall(r'^CONFIG_([^=\s]+)=(.*)$', requested, re.M))
    selections.update((symbol, 'n') for symbol in re.findall(
        r'^# CONFIG_(\S+) is not set$', requested, re.M))
    for symbol, wanted in selections.items():
        # Kconfig represents false both as an unset comment and as absence.
        actual = values.get(symbol, 'n' if wanted == 'n' else '<unset>')
        if actual != wanted:
            kind = 'package' if symbol.startswith('PACKAGE_') else 'config'
            name = symbol.removeprefix('PACKAGE_')
            raise ValueError(f'explicit {kind} selection mismatch: {name} wanted {wanted}, got {actual}')
    return defaults


if __name__ == '__main__':
    try:
        defaults = check(Path(sys.argv[1]).read_text(), Path(sys.argv[2]).read_text(),
                         Path(sys.argv[3]).read_text())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    print(f'Verified {len(defaults)} device default packages are selected (y/m)')
