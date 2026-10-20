#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -euo pipefail

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

git clone --depth=1 https://github.com/eamonxg/luci-theme-aurora.git "$stage/luci-theme-aurora" &
theme_pid=$!
git clone --depth=1 https://github.com/eamonxg/luci-app-aurora-config.git "$stage/luci-app-aurora-config" &
config_pid=$!
git clone --depth=1 --single-branch --branch main \
	https://github.com/yahuisme/packages.git "$stage/packages" &
packages_pid=$!
failed=0
for pid in "$theme_pid" "$config_pid" "$packages_pid"; do
	wait "$pid" || failed=1
done
[ "$failed" -eq 0 ] || { echo "ERROR: package download failed" >&2; exit 1; }

: > ../.custom-revisions.tsv
echo "source SHAs:"
for repo in luci-theme-aurora luci-app-aurora-config packages; do
	revision=$(git -C "$stage/$repo" rev-parse HEAD)
	printf '%s %s\n' "$repo" "$revision"
	# Record the exact fetched checkout before its temporary directory disappears.
	url=$(git -C "$stage/$repo" remote get-url origin)
	label="$repo"
	[ "$repo" != packages ] || label=yahuisme/packages
	printf '%s\t%s\t%s\n' "$label" "$url" "$revision" >> ../.custom-revisions.tsv

done

for name in luci-theme-aurora luci-app-aurora-config luci-app-homeproxy sing-box; do
	source="$stage/$name"
	case "$name" in
		luci-app-homeproxy|sing-box) source="$stage/packages/$name" ;;
	esac
	test -s "$source/Makefile" || { echo "ERROR: missing $name/Makefile" >&2; exit 1; }
done

for name in luci-theme-aurora luci-app-aurora-config luci-app-homeproxy sing-box; do
	source="$stage/$name"
	case "$name" in
		luci-app-homeproxy|sing-box) source="$stage/packages/$name" ;;
	esac
	# Remove live and dangling feed links as well as in-tree recipes.
	find . ../feeds/luci ../feeds/packages -name "$name" \( -type d -o -type l \) -prune -exec rm -rf -- {} +
	cp -a "$source" "./$name"
done

echo "Aurora, HomeProxy and sing-box installed."
