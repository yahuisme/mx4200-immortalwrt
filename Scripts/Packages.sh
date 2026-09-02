#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

#安装和更新软件包
UPDATE_PACKAGE() {
	local PKG_NAME=$1
	local PKG_REPO=$2
	local PKG_BRANCH=$3
	local PKG_SPECIAL=$4
	local PKG_LIST=("$PKG_NAME" $5)  # 第5个参数为自定义名称列表
	local REPO_NAME=${PKG_REPO#*/}

	echo " "

	# 删除本地可能存在的不同名称的软件包
	for NAME in "${PKG_LIST[@]}"; do
		# 查找匹配的目录
		echo "Search directory: $NAME"
		local FOUND_DIRS=$(find ../feeds/luci/ ../feeds/packages/ -maxdepth 3 -type d -iname "*$NAME*" 2>/dev/null)

		# 删除找到的目录
		if [ -n "$FOUND_DIRS" ]; then
			while read -r DIR; do
				rm -rf "$DIR"
				echo "Delete directory: $DIR"
			done <<< "$FOUND_DIRS"
		else
			echo "Not fonud directory: $NAME"
		fi
	done

	# 克隆 GitHub 仓库
	if ! git clone --depth=1 --single-branch --branch $PKG_BRANCH "https://github.com/$PKG_REPO.git"; then
		echo "ERROR: Failed to clone $PKG_REPO!" >&2
		exit 1
	fi

	# 处理克隆的仓库
	if [[ "$PKG_SPECIAL" == "pkg" ]]; then
		find ./$REPO_NAME/*/ -maxdepth 3 -type d -iname "*$PKG_NAME*" -prune -exec cp -rf {} ./ \;
		rm -rf ./$REPO_NAME/
	elif [[ "$PKG_SPECIAL" == "name" ]]; then
		mv -f $REPO_NAME $PKG_NAME
	fi
}

# 调用示例
# UPDATE_PACKAGE "OpenAppFilter" "destan19/OpenAppFilter" "master" "" "custom_name1 custom_name2"
# UPDATE_PACKAGE "open-app-filter" "destan19/OpenAppFilter" "master" "" "luci-app-appfilter oaf" 这样会把原有的open-app-filter，luci-app-appfilter，oaf相关组件删除，不会出现coremark错误。

# UPDATE_PACKAGE "包名" "项目地址" "项目分支" "pkg/name，可选，pkg为从大杂烩中单独提取包名插件；name为重命名为包名"
UPDATE_PACKAGE "aurora" "eamonxg/luci-theme-aurora" "master"
UPDATE_PACKAGE "aurora-config" "eamonxg/luci-app-aurora-config" "master"

# 导入 HomeProxy 与配套 sing-box（仅这两个包，最小闭包；VIKINGYFY 每日更新最新版）
rm -rf ./luci-app-homeproxy ./sing-box /tmp/viking-packages
find ../feeds/luci/ ../feeds/packages/ -maxdepth 3 -type d \
	\( -iname '*luci-app-homeproxy*' -o -iname '*sing-box*' \) -exec rm -rf {} + 2>/dev/null

if ! git clone --depth=1 --single-branch --branch main \
	https://github.com/VIKINGYFY/packages.git /tmp/viking-packages
then
	echo "ERROR: Failed to download VIKINGYFY/packages!"
	exit 1
fi

for package_name in luci-app-homeproxy sing-box; do
	if [ ! -f "/tmp/viking-packages/$package_name/Makefile" ]; then
		echo "ERROR: $package_name is missing from VIKINGYFY/packages!"
		exit 1
	fi
	cp -a "/tmp/viking-packages/$package_name" "./$package_name"
done

rm -rf /tmp/viking-packages
echo "HomeProxy and sing-box installed from VIKINGYFY/packages."

#引入私有扩展脚本
if [ -f "$GITHUB_WORKSPACE/Scripts/PRIVATE.sh" ]; then
	source "$GITHUB_WORKSPACE/Scripts/PRIVATE.sh"
fi
