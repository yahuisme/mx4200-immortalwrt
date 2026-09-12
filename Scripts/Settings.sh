#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -e

# Validate every required value before modifying the buildroot.
: "${WRT_THEME:?WRT_THEME must be non-empty}"
: "${WRT_IP:?WRT_IP must be non-empty}"
: "${WRT_SSID:?WRT_SSID must be non-empty}"
: "${WRT_WORD:?WRT_WORD must be non-empty}"

# Keep native LuCI titles/actions/ACLs; only separate the three order-90 entries.
# Validate all required menu paths before any buildroot writes.
python3 - <<'PY'
import json
from pathlib import Path

menus = (
    ('applications/luci-app-cpufreq', 'admin/system/cpufreq', 89),
    ('modules/luci-mod-system', 'admin/system/reboot', 90),
    ('applications/luci-app-advanced-reboot', 'admin/system/advanced-reboot', 91),
)
updates = []
for package, key, order in menus:
    path = Path('feeds/luci') / package / 'root/usr/share/luci/menu.d' / (Path(package).name + '.json')
    try:
        menu = json.loads(path.read_text())
        previous = menu[key]['order']
        if type(previous) is not int:
            raise ValueError('order must be an integer')
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f'ERROR: invalid required LuCI menu {path}: {error}')
    if previous != order:
        menu[key]['order'] = order
        updates.append((path, json.dumps(menu, ensure_ascii=False, indent='\t') + '\n'))
for path, text in updates:
    path.write_text(text)
PY

COLLECTION_MAKEFILES=$(find ./feeds/luci/collections/ -type f -name "Makefile" 2>/dev/null)
if [ -n "$COLLECTION_MAKEFILES" ]; then
	echo "$COLLECTION_MAKEFILES" | while IFS= read -r mkfile; do
		[ -n "$mkfile" ] || continue
		sed -i "/attendedsysupgrade/d" "$mkfile"
		sed -i "s/luci-theme-bootstrap/luci-theme-$WRT_THEME/g" "$mkfile"
	done
fi
FLASH_JS=$(find ./feeds/luci/modules/luci-mod-system/ -type f -name "flash.js" 2>/dev/null)
if [ -n "$FLASH_JS" ]; then
	sed -i "s/192\.168\.[0-9]*\.[0-9]*/$WRT_IP/g" "$FLASH_JS"
	if ! grep -Fq "$WRT_IP" "$FLASH_JS"; then
		echo "ERROR: failed to set default IP in flash.js; abort" >&2
		exit 1
	fi
else
	echo "ERROR: flash.js not found; stopping build!" >&2
	exit 1
fi
WIFI_UC="./package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc"
if [ -f "$WIFI_UC" ]; then
	sed -i "s/ssid='.*'/ssid='$WRT_SSID'/g" "$WIFI_UC"
	sed -i "s/key='.*'/key='$WRT_WORD'/g" "$WIFI_UC"
	sed -i "s/encryption='.*'/encryption='psk2+ccmp'/g" "$WIFI_UC"
	echo "wifi default ssid/key/encryption has been set!"
else
	echo "ERROR: mac80211.uc not found; stopping build!" >&2
	exit 1
fi

CFG_FILE="./package/base-files/files/bin/config_generate"
sed -i "s/192\.168\.[0-9]*\.[0-9]*/$WRT_IP/g" $CFG_FILE
if ! grep -Fq "$WRT_IP" "$CFG_FILE"; then
	echo "ERROR: failed to set default IP in config_generate; abort" >&2
	exit 1
fi

if [ -f "./include/version.mk" ]; then
	sed -i 's/ImmortalWRT/ImmortalWrt/g' ./include/version.mk
fi
sed -i 's/ImmortalWRT/ImmortalWrt/g' "$CFG_FILE"

TPL_DIR="./package/luci-app-aurora-config/root/usr/share/aurora"
if [ -d "$TPL_DIR" ]; then
	sed -i "s/nav_type '.*'/nav_type 'sidebar'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" "$TPL_DIR"/*.template 2>/dev/null || true
	echo "theme-aurora has been fixed!"
fi
