#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -e

# Aurora defaults are applied only after the required package is installed.
shopt -s nullglob
AURORA_TEMPLATES=(./package/luci-app-aurora-config/root/usr/share/aurora/*.template)
if [ "${#AURORA_TEMPLATES[@]}" -eq 0 ]; then
	echo "ERROR: Aurora templates not found" >&2
	exit 1
fi
sed -i "s/nav_type '.*'/nav_type 'sidebar'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" "${AURORA_TEMPLATES[@]}"
shopt -u nullglob

# Use native ath11k mode 1 on v2; leave all reserved-memory layouts intact.
python3 - <<'PY'
from pathlib import Path

path = Path('target/linux/qualcommax/dts/ipq8174-mx4200v2.dts')
original = b'&wifi {\n\tstatus = "okay";\n\n\tqcom,ath11k-calibration-variant = "Linksys-MX4200v2";\n};\n'
mode = b'\tqcom,ath11k-fw-memory-mode = <1>;\n'
updated = original.replace(b'};\n', mode + b'};\n')
text = path.read_bytes()
if text.count(b'&wifi') != 1:
    raise SystemExit('ERROR: unexpected MX4200v2 wifi node')
if text.count(original) == 1 and b'qcom,ath11k-fw-memory-mode' not in text:
    path.write_bytes(text.replace(original, updated))
elif text.count(updated) != 1 or text.count(b'qcom,ath11k-fw-memory-mode') != 1:
    raise SystemExit('ERROR: unexpected MX4200v2 ath11k memory mode/template')
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

sed -i "s/%D %V %C/%D %C/g" ./package/base-files/files/etc/openwrt_release
sed -i 's/%D %V %C/%D %C/g; s/^PRETTY_NAME="%D %V"$/PRETTY_NAME="%D %C"/' ./package/base-files/files/usr/lib/os-release
sed -i "s/%D %V, %C/%D %C/g" ./package/base-files/files/etc/banner

if [ -f "./include/version.mk" ]; then
	sed -i 's/ImmortalWRT/ImmortalWrt/g' ./include/version.mk
fi

