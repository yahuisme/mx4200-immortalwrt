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
