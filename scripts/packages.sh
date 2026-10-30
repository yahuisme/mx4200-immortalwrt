#!/bin/bash
# SPDX-License-Identifier: MIT
set -euo pipefail

# Source packages and signed Aurora APKs use separate provenance boundaries.
rm -f ../.custom-revisions.tsv
stage=$(mktemp -d -t mx4200-packages.XXXXXXXX)
trap 'rm -rf "$stage"' EXIT
git clone --depth=1 --single-branch --branch main \
    https://github.com/yahuisme/packages.git "$stage/packages"
for name in luci-app-homeproxy sing-box; do
    test -s "$stage/packages/$name/Makefile" || { echo "ERROR: missing $name/Makefile" >&2; exit 1; }
done
revision=$(git -C "$stage/packages" rev-parse HEAD)
url=$(git -C "$stage/packages" remote get-url origin)
for name in luci-app-homeproxy sing-box; do
    # Remove duplicate recipes and dangling feeds/install links before reindexing.
    find . ../feeds/luci ../feeds/packages -name "$name" \
        \( -type d -o -type l \) -prune -exec rm -rf -- {} +
    cp -a "$stage/packages/$name" "./$name"
done
python3 /cache-scripts/external_packages.py prepare ..
printf 'yahuisme/packages\t%s\t%s\n' "$url" "$revision" > ../.custom-revisions.tsv
echo "HomeProxy and sing-box source: $revision"
