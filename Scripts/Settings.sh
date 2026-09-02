#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -e

#移除luci-app-attendedsysupgrade（验证结果，失败即停）
COLLECTION_MAKEFILES=$(find ./feeds/luci/collections/ -type f -name "Makefile")
sed -i "/attendedsysupgrade/d" $COLLECTION_MAKEFILES
if grep -q "attendedsysupgrade" $COLLECTION_MAKEFILES; then
    echo "ERROR: attendedsysupgrade still referenced in luci collections; abort" >&2
    exit 1
fi
#修改默认主题（验证结果，失败即停）
sed -i "s/luci-theme-bootstrap/luci-theme-$WRT_THEME/g" $COLLECTION_MAKEFILES
if grep -q "luci-theme-bootstrap" $COLLECTION_MAKEFILES; then
    echo "ERROR: luci-theme-bootstrap still referenced in luci collections; abort" >&2
    exit 1
fi
#修改immortalwrt.lan关联IP（验证结果，失败即停）
FLASH_JS=$(find ./feeds/luci/modules/luci-mod-system/ -type f -name "flash.js")
sed -i "s/192\.168\.[0-9]*\.[0-9]*/$WRT_IP/g" $FLASH_JS
if ! grep -Fq "$WRT_IP" $FLASH_JS; then
    echo "ERROR: failed to set default IP in flash.js; abort" >&2
    exit 1
fi
#添加编译日期标识（验证结果，失败即停）
SYSTEM_JS=$(find ./feeds/luci/modules/luci-mod-status/ -type f -name "10_system.js")
sed -i "s/(\(luciversion || ''\))/(\1) + (' \/ $WRT_DATE')/g" $SYSTEM_JS
if ! grep -Fq "$WRT_DATE" $SYSTEM_JS; then
    echo "ERROR: failed to inject build date into 10_system.js; abort" >&2
    exit 1
fi

WIFI_SH=$(find ./target/linux/{mediatek/filogic,qualcommax}/base-files/etc/uci-defaults/ -type f -name "*set-wireless.sh" 2>/dev/null)
WIFI_UC="./package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc"
if [ -f "$WIFI_SH" ]; then
	#修改WIFI名称
	sed -i "s/BASE_SSID='.*'/BASE_SSID='$WRT_SSID'/g" $WIFI_SH
	#修改WIFI密码
	sed -i "s/BASE_WORD='.*'/BASE_WORD='$WRT_WORD'/g" $WIFI_SH
	#验证生效，失败即停（避免上游改格式后静默退回默认 SSID）
	if grep -Fq "BASE_SSID='$WRT_SSID'" "$WIFI_SH" && grep -Fq "BASE_WORD='$WRT_WORD'" "$WIFI_SH"; then
		echo "wifi default ssid/key has been set! (set-wireless.sh)"
	else
		echo "ERROR: failed to set wifi default ssid/key in set-wireless.sh; stopping build!" >&2
		exit 1
	fi
elif [ -f "$WIFI_UC" ]; then
	#修改WIFI名称
	sed -i "s/ssid='.*'/ssid='$WRT_SSID'/g" $WIFI_UC
	#修改WIFI密码
	sed -i "s/key='.*'/key='$WRT_WORD'/g" $WIFI_UC
	#验证生效，失败即停（避免上游改格式后静默退回默认 SSID）
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
#修改默认IP地址
sed -i "s/192\.168\.[0-9]*\.[0-9]*/$WRT_IP/g" $CFG_FILE
#修改默认主机名
sed -i "s/hostname='.*'/hostname='$WRT_NAME'/g" $CFG_FILE
#验证生效，失败即停
if ! grep -Fq "$WRT_IP" "$CFG_FILE" || ! grep -Fq "hostname='$WRT_NAME'" "$CFG_FILE"; then
    echo "ERROR: failed to set default IP/hostname in config_generate; abort" >&2
    exit 1
fi

#拷贝 MX4200 首启默认脚本（机型主机名/时区/无线默认）
mkdir -p ./package/base-files/files/etc/uci-defaults/
cp "$GITHUB_WORKSPACE/files/etc/uci-defaults/99-mx4200-defaults" ./package/base-files/files/etc/uci-defaults/99-mx4200-defaults
chmod +x ./package/base-files/files/etc/uci-defaults/99-mx4200-defaults

#配置文件修改
echo "CONFIG_PACKAGE_luci=y" >> ./.config
echo "CONFIG_LUCI_LANG_zh_Hans=y" >> ./.config

#引入私有扩展配置
if [ -f "$GITHUB_WORKSPACE/Config/PRIVATE.txt" ]; then
	echo "Applying private configurations from PRIVATE.txt..."
	cat $GITHUB_WORKSPACE/Config/PRIVATE.txt >> ./.config
fi

#手动调整的插件
if [ -n "$WRT_PACKAGE" ]; then
	echo -e "$WRT_PACKAGE" >> ./.config
fi

#无WIFI配置标志
if [[ "${WRT_CONFIG,,}" == *"wifi"* && "${WRT_CONFIG,,}" == *"no"* ]]; then
	echo "WRT_WIFI=wifi-no" >> $GITHUB_ENV
fi

#高通平台调整
DTS_PATH="./target/linux/qualcommax/dts/"
if [[ "${WRT_TARGET^^}" == *"QUALCOMMAX"* ]]; then
	#无WIFI配置调整Q6大小
	if [[ "${WRT_CONFIG,,}" == *"wifi"* && "${WRT_CONFIG,,}" == *"no"* ]]; then
		find $DTS_PATH -type f ! -iname '*nowifi*' -exec sed -i 's/ipq\(6018\|8074\).dtsi/ipq\1-nowifi.dtsi/g' {} +
		echo "qualcommax set up nowifi successfully!"
	fi
fi
