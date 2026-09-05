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
		"https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set-unstable/geosite-cn.srs" -o "$HP_RESOURCES/geosite_cn.srs"; then
		echo "homeproxy resources: geosite_cn updated"
	else
		echo "WARNING: failed to fetch geosite_cn, skipping"
	fi

	# 3. 下载 Web 控制面板
	if curl -fsSL --retry 3 --connect-timeout 10 --max-time 60 \
		"https://codeload.github.com/SagerNet/sing-box-dashboard/zip/refs/heads/gh-pages" -o "$HP_TMP/dashboard.zip"; then
		unzip -qo "$HP_TMP/dashboard.zip" -d "$HP_TMP/"
		DASHBOARD_SRC="$(find "$HP_TMP" -mindepth 1 -maxdepth 1 -type d -name '*dashboard*' -print -quit)"
		if [ -n "$DASHBOARD_SRC" ] && [ -f "$DASHBOARD_SRC/index.html" ]; then
			cp -rf "$DASHBOARD_SRC"/* "$HP_DASHBOARD/"
			echo "homeproxy dashboard updated"
		fi
	else
		echo "WARNING: failed to fetch dashboard, skipping"
	fi

	rm -rf "$HP_TMP"
	trap - EXIT INT TERM
fi

# 修改 Aurora 菜单式样（验证结果，失败即停）
if [ ! -d "$PKG_PATH/luci-app-aurora-config" ]; then
	echo "ERROR: luci-app-aurora-config missing" >&2
	exit 1
fi
echo " "
TPL_DIR="$PKG_PATH/luci-app-aurora-config/root/usr/share/aurora/"
if ! ls "$TPL_DIR"/*.template >/dev/null 2>&1; then
	echo "ERROR: aurora templates missing" >&2
	exit 1
fi
sed -i "s/nav_type '.*'/nav_type 'sidebar'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" "$TPL_DIR"/*.template
if grep -q "nav_type 'sidebar'" "$TPL_DIR"/*.template; then
	echo "theme-aurora has been fixed!"
else
	echo "ERROR: theme-aurora fix failed" >&2
	exit 1
fi

