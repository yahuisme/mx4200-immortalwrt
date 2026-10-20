#!/usr/bin/env python3
"""Keep one unavailable Wi-Fi hwmon from hiding other readable sensors."""
from pathlib import Path
import sys

OLD = '''\twifi_temp="$(awk '{printf("%.1f°C ", $0 / 1000)}' "$IEEE_PATH"/phy*/hwmon*/temp1_input 2>"/dev/null" | awk '$1=$1')"'''
NEW = '''\twifi_temp="$(
\t\tfor sensor in "$IEEE_PATH"/phy*/hwmon*/temp1_input; do
\t\t\t[ -r "$sensor" ] || continue
\t\t\tawk '/^-?[0-9]+$/ {printf("%.1f°C ", $0 / 1000)}' "$sensor" 2>/dev/null
\t\tdone | awk '$1=$1'
\t)"'''


def prepare(root):
    path = Path(root) / 'package/emortal/autocore/files/tempinfo'
    text = path.read_text()
    if text.count(NEW) == 1 and OLD not in text:
        return
    if text.count(OLD) != 1:
        raise SystemExit('ERROR: unknown autocore Wi-Fi temperature reader; review upstream')
    path.write_text(text.replace(OLD, NEW))


if __name__ == '__main__':
    prepare(sys.argv[1])
