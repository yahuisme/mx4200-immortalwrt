#!/usr/bin/env python3
"""Use the official feed's bootstrap version, not the runner's ambient Go."""
import os
from pathlib import Path
import re
import sys


def main():
    recipe = (Path(sys.argv[1]) / 'feeds/packages/lang/golang/golang-bootstrap/Makefile').read_text()
    values = []
    for field, pattern in [('GO_VERSION_MAJOR_MINOR', r'[0-9]+\.[0-9]+'),
                           ('GO_VERSION_PATCH', r'[0-9]+')]:
        matches = re.findall(r'^' + field + r':=(' + pattern + r')\s*$', recipe, re.M)
        if len(matches) != 1:
            raise ValueError('Unsupported official bootstrap version: ' + field)
        values.append(matches[0])
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('version=' + '.'.join(values) + '\n')


if __name__ == '__main__':
    main()
