#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

# 拉取 Aurora 主题与配置插件
rm -rf ./luci-theme-aurora ./luci-app-aurora-config
git clone --depth=1 "https://github.com/eamonxg/luci-theme-aurora.git" ./luci-theme-aurora
git clone --depth=1 "https://github.com/eamonxg/luci-app-aurora-config.git" ./luci-app-aurora-config

# 从 yahuisme/packages 拉取定制版 HomeProxy 与 sing-box
rm -rf ./luci-app-homeproxy ./sing-box /tmp/yahuisme-packages
find ../feeds/luci/ ../feeds/packages/ -maxdepth 3 -type d \
	\( -iname '*luci-app-homeproxy*' -o -iname '*sing-box*' \) -exec rm -rf {} + 2>/dev/null

if git clone --depth=1 --single-branch --branch main \
	https://github.com/yahuisme/packages.git /tmp/yahuisme-packages; then
	for package_name in luci-app-homeproxy sing-box luci-app-firmwareupgrade; do
		if [ -d "/tmp/yahuisme-packages/$package_name" ]; then
			cp -a "/tmp/yahuisme-packages/$package_name" "./$package_name"
		fi
	done
	rm -rf /tmp/yahuisme-packages
	echo "HomeProxy and sing-box installed from yahuisme/packages."
else
	echo "ERROR: Failed to download yahuisme/packages!" >&2
	exit 1
fi
