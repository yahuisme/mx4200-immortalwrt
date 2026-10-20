#!/usr/bin/env python3
"""Check the pinned external Go against the prepared official feed's floor."""
from pathlib import Path
import re
import subprocess
import sys


def check(root, bootstrap):
    recipe = (Path(root) / 'feeds/packages/lang/golang/golang-bootstrap/Makefile').read_text()
    values = []
    for field, pattern in [('GO_VERSION_MAJOR_MINOR', r'[0-9]+\.[0-9]+'),
                           ('GO_VERSION_PATCH', r'[0-9]+')]:
        matches = re.findall(r'^' + field + r':=(' + pattern + r')[ \t]*$', recipe, re.M)
        if len(matches) != 1:
            raise ValueError('Unsupported official bootstrap floor: ' + field)
        values.append(matches[0])
    floor = tuple(map(int, '.'.join(values).split('.')))
    # GOTOOLCHAIN=local prevents implicit downloads from satisfying the check.
    import os
    actual = subprocess.check_output([str(Path(bootstrap) / 'bin/go'), 'version'],
                                    env=dict(os.environ, GOTOOLCHAIN='local'), text=True).strip()
    match = re.fullmatch(r'go version go([0-9]+)\.([0-9]+)\.([0-9]+) linux/arm64', actual)
    if not match:
        raise ValueError('Unsupported external bootstrap: ' + actual)
    version = tuple(map(int, match.groups()))
    if version < floor:
        raise ValueError(f'External Go {version} is below official feed floor {floor}')
    print(f'External bootstrap: {actual}; official feed floor: ' + '.'.join(map(str, floor)))
    return version, floor


if __name__ == '__main__':
    check(*sys.argv[1:])
