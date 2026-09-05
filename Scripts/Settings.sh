#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -e

COLLECTION_MAKEFILES=$(find ./feeds/luci/collections/ -type f -name "Makefile")
sed -i "/attendedsysupgrade/d" $COLLECTION_MAKEFILES
if grep -q "attendedsysupgrade" $COLLECTION_MAKEFILES; then
	echo "ERROR: attendedsysupgrade still referenced in luci collections; abort" >&2
	exit 1
fi
sed -i "s/luci-theme-bootstrap/luci-theme-$WRT_THEME/g" $COLLECTION_MAKEFILES
if grep -q "luci-theme-bootstrap" $COLLECTION_MAKEFILES; then
	echo "ERROR: luci-theme-bootstrap still referenced in luci collections; abort" >&2
	exit 1
fi
FLASH_JS=$(find ./feeds/luci/modules/luci-mod-system/ -type f -name "flash.js")
sed -i "s/192\.168\.[0-9]*\.[0-9]*/$WRT_IP/g" $FLASH_JS
if ! grep -Fq "$WRT_IP" $FLASH_JS; then
	echo "ERROR: failed to set default IP in flash.js; abort" >&2
	exit 1
fi
WIFI_SH=$(find ./target/linux/{mediatek/filogic,qualcommax}/base-files/etc/uci-defaults/ -type f -name "*set-wireless.sh" 2>/dev/null)
WIFI_UC="./package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc"
if [ -f "$WIFI_SH" ]; then
	sed -i "s/BASE_SSID='.*'/BASE_SSID='$WRT_SSID'/g" $WIFI_SH
	sed -i "s/BASE_WORD='.*'/BASE_WORD='$WRT_WORD'/g" $WIFI_SH
	if grep -Fq "BASE_SSID='$WRT_SSID'" "$WIFI_SH" && grep -Fq "BASE_WORD='$WRT_WORD'" "$WIFI_SH"; then
		echo "wifi default ssid/key has been set! (set-wireless.sh)"
	else
		echo "ERROR: failed to set wifi default ssid/key in set-wireless.sh; stopping build!" >&2
		exit 1
	fi
elif [ -f "$WIFI_UC" ]; then
	sed -i "s/ssid='.*'/ssid='$WRT_SSID'/g" $WIFI_UC
	sed -i "s/key='.*'/key='$WRT_WORD'/g" $WIFI_UC
	if grep -Fq "ssid='$WRT_SSID'" "$WIFI_UC" && grep -Fq "key='$WRT_WORD'" "$WIFI_UC"; then
		echo "wifi default ssid/key has been set!"
	else
		echo "ERROR: failed to set wifi default ssid/key in mac80211.uc; stopping build!" >&2
		exit 1
	fi
else
	echo "ERROR: no wifi default script found (set-wireless.sh or mac80211.uc); stopping build!" >&2
	exit 1
fi

CFG_FILE="./package/base-files/files/bin/config_generate"
sed -i "s/192\.168\.[0-9]*\.[0-9]*/$WRT_IP/g" $CFG_FILE
sed -i "s/hostname='.*'/hostname='$WRT_NAME'/g" $CFG_FILE
if ! grep -Fq "$WRT_IP" "$CFG_FILE" || ! grep -Fq "hostname='$WRT_NAME'" "$CFG_FILE"; then
	echo "ERROR: failed to set default IP/hostname in config_generate; abort" >&2
	exit 1
fi

sed -i "s/%D %V %C/%D %C/g" ./package/base-files/files/etc/openwrt_release
sed -i "s/%D %V %C/%D %C/g" ./package/base-files/files/usr/lib/os-release
sed -i "s/%D %V, %C/%D %C/g" ./package/base-files/files/etc/banner

if [ -f "./include/version.mk" ]; then
	sed -i 's/VERSION_DIST,ImmortalWRT/VERSION_DIST,ImmortalWrt/g' ./include/version.mk
	sed -i 's/VERSION_MANUFACTURER,ImmortalWRT/VERSION_MANUFACTURER,ImmortalWrt/g' ./include/version.mk
fi

mkdir -p ./package/base-files/files/etc/uci-defaults/
cp "$GITHUB_WORKSPACE/files/etc/uci-defaults/99-mx4200-defaults" ./package/base-files/files/etc/uci-defaults/99-mx4200-defaults
chmod +x ./package/base-files/files/etc/uci-defaults/99-mx4200-defaults
