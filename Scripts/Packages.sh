#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 VIKINGYFY
set -euo pipefail
# Executed inside buildroot/package, never in the orchestration checkout.
test -f ../rules.mk
# Core packages are installed in-tree by Prepare.py, not a rolling NSS feed.
for name in qca-nss-drv qca-nss-ecm qca-nss-clients nss-firmware; do
    test -f "qca-nss/$name/Makefile"
done
test ! -d ../feeds/nss_packages
for name in luci-theme-aurora luci-app-aurora-config; do
    test ! -e "./$name"
    git clone --depth=1 "https://github.com/eamonxg/$name.git" "./$name"
done
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
git clone --depth=1 --single-branch --branch main https://github.com/VIKINGYFY/packages.git "$stage/packages"
for name in luci-app-homeproxy sing-box; do
    test -f "$stage/packages/$name/Makefile"
    test ! -e "./$name"
done
# Remove only the two overridden official feed packages and their install links.
rm -rf ../feeds/luci/applications/luci-app-homeproxy ../feeds/packages/net/sing-box
# scripts/feeds installs links under package/feeds; cwd is already package.
rm -f ./feeds/luci/luci-app-homeproxy ./feeds/packages/sing-box
for link in ./feeds/luci/luci-app-homeproxy ./feeds/packages/sing-box; do
    test ! -e "$link" && test ! -L "$link"
done
for name in luci-app-homeproxy sing-box; do
    cp -a "$stage/packages/$name" "./$name"
done

# Preset HomeProxy resources from the upstream sing-box feeds.
hp_preset_resources() {
    local hp_dir="$1" tmp resource version url
    local resources="$hp_dir/root/etc/homeproxy/resources"
    local dashboard="$hp_dir/root/etc/homeproxy/dashboard"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN
    mkdir -p "$resources" "$dashboard"
    for resource in geoip_cn geosite_cn; do
        case "$resource" in
            geoip_cn) url=https://cdn.jsdelivr.net/gh/SagerNet/sing-geoip@rule-set/geoip-cn.srs ;;
            geosite_cn) url=https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set-unstable/geosite-cn.srs ;;
        esac
        curl -fsSL --retry 3 --retry-all-errors --connect-timeout 10 --max-time 60 -o "$tmp/$resource.srs" "$url"
        test "$(head -c 3 "$tmp/$resource.srs")" = SRS
        test "$(wc -c < "$tmp/$resource.srs")" -gt 4
        mv "$tmp/$resource.srs" "$resources/$resource.srs"
        printf '%s\n' "$(date -u +%Y%m%d)" > "$resources/$resource.ver"
    done
    curl -fsSL --retry 3 --retry-all-errors --connect-timeout 10 --max-time 60 \
        -o "$tmp/dashboard.zip" https://codeload.github.com/SagerNet/sing-box-dashboard/zip/refs/heads/gh-pages
    rm -rf "$tmp/dashboard"; mkdir "$tmp/dashboard"
    unzip -q "$tmp/dashboard.zip" -d "$tmp/dashboard"
    local index source
    index="$(find "$tmp/dashboard" -name index.html -type f -print -quit)"
    test -s "$index"; source="${index%/index.html}"
    rm -rf "$dashboard.new"; mkdir "$dashboard.new"
    cp -a "$source/." "$dashboard.new/"
    rm -f "$dashboard.new/.etag"
    printf '%s\n' "$(date -u +%Y%m%d%H%M%S)" > "$dashboard.new/dashboard.ver"
    rm -rf "$dashboard"; mv "$dashboard.new" "$dashboard"
    chmod -R a+rX "$resources" "$dashboard"
}

hp_preset_resources ./luci-app-homeproxy

python3 - "$stage/packages" "$(dirname "$(readlink -f "$0")")" <<'PY'
import json, pathlib, subprocess, sys
sys.path.insert(0, sys.argv[2])
from Inputs import record
lock = pathlib.Path('../source-lock.json')
data = json.loads(lock.read_text())
data['custom_packages'] = {name: subprocess.check_output(['git', '-C', path, 'rev-parse', 'HEAD'], text=True).strip()
                           for name, path in [('aurora', 'luci-theme-aurora'), ('aurora-config', 'luci-app-aurora-config'), ('VIKINGYFY/packages', sys.argv[1])]}
# Record what was actually cloned, not an earlier scheduled probe.
record(data, {'aurora': pathlib.Path('luci-theme-aurora'),
              'aurora-config': pathlib.Path('luci-app-aurora-config'),
              'VIKINGYFY/packages': pathlib.Path(sys.argv[1])})
lock.write_text(json.dumps(data, indent=2) + '\n')
PY
