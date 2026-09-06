#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

PKG_PATH="$(pwd)"

# 预置 HomeProxy 数据
HP_DIR="$(find "$PKG_PATH" -maxdepth 3 -type d -iname '*homeproxy*' -print -quit 2>/dev/null)"
if [ -n "$HP_DIR" ]; then
	HP_RESOURCES="$HP_DIR/root/etc/homeproxy/resources"
	HP_DASHBOARD="$HP_DIR/root/etc/homeproxy/dashboard"
	mkdir -p "$HP_RESOURCES" "$HP_DASHBOARD"

	echo "Fetching HomeProxy preset resources..."
	HP_TMP="$(mktemp -d)"
	trap 'rm -rf "$HP_TMP"' EXIT INT TERM

	# 1. 下载中国 IP CIDR 并转换为 rules 格式
	if curl -fsSL --retry 3 --connect-timeout 10 --max-time 30 \
		"https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/cncidr.txt" -o "$HP_TMP/cncidr.txt"; then
		awk -F, -v v4="$HP_TMP/china_ip4.txt" -v v6="$HP_TMP/china_ip6.txt" '
			$1 == "IP-CIDR" { print $2 > v4 }
			$1 == "IP-CIDR6" { print $2 > v6 }
		' "$HP_TMP/cncidr.txt"

		awk '
			BEGIN { print "{\"version\":5,\"rules\":[{\"ip_cidr\":["; first = 1 }
			NF { printf "%s\"%s\"", first ? "" : ",", $0; first = 0 }
			END { print "]}]}" }
		' "$HP_TMP/china_ip4.txt" "$HP_TMP/china_ip6.txt" > "$HP_TMP/geoip_cn.json"

		cp -f "$HP_TMP/china_ip4.txt" "$HP_TMP/china_ip6.txt" "$HP_TMP/geoip_cn.json" "$HP_RESOURCES/"
		echo "homeproxy resources: china_ip updated"
	else
		echo "WARNING: failed to fetch cn cidr, skipping"
	fi

	# 2. 下载 geosite 规则集
	if curl -fsSL --retry 3 --connect-timeout 10 --max-time 30 \
		"https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-cn.srs" -o "$HP_RESOURCES/geosite_cn.srs"; then
		echo "homeproxy resources: geosite_cn updated"
	else
		echo "WARNING: failed to fetch geosite_cn, skipping"
	fi

	rm -rf "$HP_TMP"
	trap - EXIT INT TERM
fi

TPL_DIR="$PKG_PATH/luci-app-aurora-config/root/usr/share/aurora"
if [ -d "$TPL_DIR" ]; then
	sed -i "s/nav_type '.*'/nav_type 'sidebar'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" "$TPL_DIR"/*.template 2>/dev/null || true
	echo "theme-aurora has been fixed!"
fi

