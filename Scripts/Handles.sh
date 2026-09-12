#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY

set -e

PKG_PATH="$(pwd)"

TPL_DIR="$PKG_PATH/luci-app-aurora-config/root/usr/share/aurora"
if [ -d "$TPL_DIR" ]; then
	sed -i "s/nav_type '.*'/nav_type 'sidebar'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" "$TPL_DIR"/*.template 2>/dev/null || true
	echo "theme-aurora has been fixed!"
fi
