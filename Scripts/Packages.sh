#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

UPDATE_PACKAGE() {
	local PKG_NAME=$1
	local PKG_REPO=$2
	local PKG_BRANCH=$3
	local PKG_SPECIAL=$4
	local PKG_LIST=("$PKG_NAME" $5)
	local REPO_NAME=${PKG_REPO#*/}

	for NAME in "${PKG_LIST[@]}"; do
		local FOUND_DIRS=$(find ../feeds/luci/ ../feeds/packages/ -maxdepth 3 -type d -iname "*$NAME*" 2>/dev/null)
		if [ -n "$FOUND_DIRS" ]; then
			while read -r DIR; do
				rm -rf "$DIR"
			done <<< "$FOUND_DIRS"
		fi
	done

	if ! git clone --depth=1 --single-branch --branch $PKG_BRANCH "https://github.com/$PKG_REPO.git"; then
		echo "ERROR: Failed to clone $PKG_REPO!" >&2
		exit 1
	fi

	if [[ "$PKG_SPECIAL" == "pkg" ]]; then
		find ./$REPO_NAME/*/ -maxdepth 3 -type d -iname "*$PKG_NAME*" -prune -exec cp -rf {} ./ \;
		rm -rf ./$REPO_NAME/
	elif [[ "$PKG_SPECIAL" == "name" ]]; then
		mv -f $REPO_NAME $PKG_NAME
	fi
}

UPDATE_PACKAGE "aurora" "eamonxg/luci-theme-aurora" "master"
UPDATE_PACKAGE "aurora-config" "eamonxg/luci-app-aurora-config" "master"

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
