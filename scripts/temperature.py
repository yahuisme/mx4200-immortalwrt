#!/usr/bin/env python3
"""Keep an inactive Wi-Fi sensor from hiding readable radios."""
from pathlib import Path
import sys

OLD = '''\twifi_temp="$(awk '{printf("%.1f°C ", $0 / 1000)}' "$IEEE_PATH"/phy*/hwmon*/temp1_input 2>"/dev/null" | awk '$1=$1')"'''
NEW = '''\twifi_temp="$(
\t\tfor sensor in "$IEEE_PATH"/phy*/hwmon*/temp1_input; do
\t\t\tread -r value 2>/dev/null < "$sensor" || continue
\t\t\tprintf '%s\\n' "$value"
\t\tdone | awk '/^-?[0-9]+$/ {printf("%s%.1f°C", sep, $0 / 1000); sep=" "}'
\t)"'''


def prepare(root):
    path = Path(root) / 'package/emortal/autocore/files/tempinfo'
    text = path.read_text()
    if text.count(OLD) == 1 and NEW not in text:
        path.write_text(text.replace(OLD, NEW, 1))
    elif text.count(NEW) != 1 or OLD in text:
        raise ValueError('Unsupported autocore Wi-Fi temperature reader')


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except (IndexError, OSError, ValueError) as error:
        sys.exit(f'ERROR: {error}')
