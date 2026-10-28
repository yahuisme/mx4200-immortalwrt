#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -e

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

# Keep upstream stable version placeholders intact.
if [ -f "./include/version.mk" ]; then
	sed -i 's/ImmortalWRT/ImmortalWrt/g' ./include/version.mk
fi

