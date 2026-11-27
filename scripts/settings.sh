#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -euo pipefail

python3 - <<'PY'
import ipaddress
import json
import os
from pathlib import Path
import re

ip = str(ipaddress.IPv4Address(os.environ['WRT_IP']))
ssid, key = (os.environ[name] for name in ('WRT_SSID', 'WRT_WORD'))
# These values go in UCI single quotes inside a ucode backtick template.
if any(not re.fullmatch(r"[^'`\\\r\n]+", v) or '${' in v for v in (ssid, key)):
    raise SystemExit('Invalid wireless default for ucode template')

originals, updates = {}, {}

def read(name):
    path = Path(name)
    if not path.is_file():
        raise SystemExit(f'{path.name} not found: {path}')
    originals[path] = path.read_text()
    return path, originals[path]


def replace_line(text, old, new, label, active=None):
    lines = text.splitlines(keepends=True)
    active_lines = (text if active is None else active).splitlines()
    candidates = [i for i, line in enumerate(active_lines) if line in (old, new)]
    if len(candidates) != 1:
        raise SystemExit(f'Unsupported source boundary: {label}')
    i = candidates[0]
    if lines[i].rstrip('\n') != active_lines[i]:
        raise SystemExit(f'Unsupported source boundary: {label}')
    lines[i] = lines[i].replace(old, new, 1)
    return ''.join(lines)


# Preserve quoted strings, including URL literals and ucode templates. Mask
# comments without shifting any original line/column positions.
def without_comments(text):
    tokens = r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|/\*.*?\*/|//[^\n]*'''
    return re.sub(tokens, lambda m: re.sub(r'[^\n]', ' ', m[0]) if m[0].startswith('/') else m[0],
                  text, flags=re.S)


path, text = read('feeds/luci/modules/luci-mod-system/htdocs/luci-static/resources/view/system/flash.js')
active = without_comments(text)
for indent, prefix in ((2, ''), (4, 'window.location.host, '), (3, 'window.location.host, ')):
    old = '\t' * indent + f"ui.awaitReconnect({prefix}'192.168.1.1', 'immortalwrt.lan');"
    # The three anchors are distinct whole lines; replacing one cannot shift the others.
    text = replace_line(text, old, old.replace('192.168.1.1', ip), 'flash.js reconnect', active)
updates[path] = text

# Keep the native menu package-owned and change only its intended field.
path, text = read('feeds/luci/applications/luci-app-advanced-reboot/root/usr/share/luci/menu.d/luci-app-advanced-reboot.json')
menu = json.loads(text)
route = menu.get('admin/system/advanced-reboot')
if not isinstance(route, dict) or type(route.get('order')) is not int or route['order'] not in (90, 91):
    raise SystemExit('Unsupported Advanced Reboot menu order')
if route['order'] == 90:
    route['order'] = 91
    updates[path] = json.dumps(menu, indent='\t', ensure_ascii=False) + '\n'

# Aurora is supplied as signed APKs; remove only the reviewed theme token.
# Attended Sysupgrade is already deselected in config.diff.
path, text = read('feeds/luci/collections/luci-light/Makefile')
theme = '\t+luci-theme-bootstrap \\\n'
if text.count(theme) > 1:
    raise SystemExit('Ambiguous luci-light theme dependency')
updated = text.replace(theme, '', 1)
if any('luci-theme-bootstrap' in line.split('#', 1)[0] for line in updated.splitlines()):
    raise SystemExit('Unsupported luci-light theme dependency')
updates[path] = updated

path, text = read('package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc')
start = "\nset ${si}=wifi-iface\nset ${si}.device='${name}'\n"
end = "\nset ${si}.disabled='0'\n\n`);"
active = without_comments(text)
if active.count(start) != 1 or active.count(end) != 1:
    raise SystemExit('Unsupported wireless generator template')
first = active.index(start) + len(start)
last = active.index(end, first)
block = text[first:last]
for name, native, val in (('ssid', '${defaults?.ssid || "ImmortalWrt"}', ssid),
                          ('encryption', '${defaults?.encryption || encryption}', 'psk2+ccmp'),
                          ('key', '${defaults?.key || ""}', key)):
    prefix = 'set ${si}.' + name
    block = replace_line(block, f"{prefix}='{native}'", f"{prefix}='{val}'", f'failed to set default wireless {name}')
updates[path] = text[:first] + block + text[last:]

path, text = read('package/base-files/files/bin/config_generate')
old = '\t\t\t\tlan) ipad=${ipaddr:-"192.168.1.1"} ;;'
updates[path] = replace_line(text, old, old.replace('192.168.1.1', ip), 'config_generate LAN default')

# Validate every boundary before touching the tree.
for path, text in updates.items():
    if originals[path] != text:
        path.write_text(text)
PY
