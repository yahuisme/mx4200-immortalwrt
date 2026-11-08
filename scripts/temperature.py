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


CPU_OLD = '''\t;;
*)
\tcpu_temp="$(awk '{printf("%.1f°C", $0 / 1000)}' "$THERMAL_PATH/thermal_zone0/temp" 2>"/dev/null")"'''
CPU_NEW = '''\t;;
qualcommax/ipq807x)
\tcpu_temp="$(
\t\tfor kind in cpu0-thermal cluster-thermal; do
\t\t\tfor zone in "$THERMAL_PATH"/thermal_zone*; do
\t\t\t\tvalue="$(awk -v wanted="$kind" '
\t\t\t\t\tFILENAME ~ /\\/type$/ {kind=$0; next}
\t\t\t\t\tkind == wanted && /^-?[0-9]+$/ {printf("%.1f°C", $0 / 1000)}
\t\t\t\t' "$zone/type" "$zone/temp" 2>/dev/null)"
\t\t\t\t[ -n "$value" ] || continue
\t\t\t\tprintf '%s' "$value"
\t\t\t\texit
\t\t\tdone
\t\tdone
\t)"
\t;;
*)
\tcpu_temp="$(awk '{printf("%.1f°C", $0 / 1000)}' "$THERMAL_PATH/thermal_zone0/temp" 2>"/dev/null")"'''


def prepare(root):
    path = Path(root) / 'package/emortal/autocore/files/tempinfo'
    text = path.read_text()
    for old, new in ((OLD, NEW), (CPU_OLD, CPU_NEW)):
        if text.count(new) == 1 and text.count(old) == new.count(old):
            continue
        if text.count(old) != 1:
            raise SystemExit('ERROR: unknown autocore temperature reader; review upstream')
        text = text.replace(old, new)
    path.write_text(text)


if __name__ == '__main__':
    prepare(sys.argv[1])
