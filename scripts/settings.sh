#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -e

# Keep the menu package-owned so per-device removal leaves no orphan entry.
ADVANCED_MENU=feeds/luci/applications/luci-app-advanced-reboot/root/usr/share/luci/menu.d/luci-app-advanced-reboot.json
[ -s "$ADVANCED_MENU" ] || { echo "ERROR: Advanced Reboot menu not found" >&2; exit 1; }
cp "${DK_PROFILE:-$(dirname "$0")/../user/default}/menus/luci-app-advanced-reboot.json" "$ADVANCED_MENU"

COLLECTION_MAKEFILES=$(find ./feeds/luci/collections/ -type f -name "Makefile" 2>/dev/null)
if [ -n "$COLLECTION_MAKEFILES" ]; then
	echo "$COLLECTION_MAKEFILES" | while IFS= read -r mkfile; do
		[ -n "$mkfile" ] || continue
		sed -i "/attendedsysupgrade/d" "$mkfile"
		# Aurora is installed as a signed APK after local package assembly.
		# Remove the default theme dependency; do not reference a source recipe.
		sed -i 's/+\{0,1\}luci-theme-bootstrap\> */ /g' "$mkfile"
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
	if ! grep -Fxq "set \${si}.ssid='$WRT_SSID'" "$WIFI_UC"; then
		echo "ERROR: failed to set default wireless ssid; abort" >&2
		exit 1
	fi
	if ! grep -Fxq "set \${si}.key='$WRT_WORD'" "$WIFI_UC"; then
		echo "ERROR: failed to set default wireless key; abort" >&2
		exit 1
	fi
	if ! grep -Fxq "set \${si}.encryption='psk2+ccmp'" "$WIFI_UC"; then
		echo "ERROR: failed to set default wireless encryption; abort" >&2
		exit 1
	fi
	echo "wifi default ssid/key has been set!"
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

# Keep official version templates and machine/feed identifiers unchanged.

