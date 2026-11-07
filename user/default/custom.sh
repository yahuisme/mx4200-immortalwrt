#!/bin/bash
set -euo pipefail
export WRT_THEME=aurora WRT_SSID=MX4200 WRT_WORD=12345678 WRT_IP=192.168.10.1
# Reject unreviewed sources before mirror, package or provenance writes.
python3 /cache-scripts/external_packages.py preflight "$DK_OPENWRT"
python3 /cache-scripts/homewrk_dts.py "$DK_OPENWRT"
# Keep mirror selection and firmware customization independent of the runner.
if [ -f scripts/projectsmirrors.json ]; then
    sed -i '/.cn\//d; /tencent/d; /aliyun/d' scripts/projectsmirrors.json
fi
(cd package && bash /cache-scripts/packages.sh)
python3 /cache-scripts/temperature.py "$DK_OPENWRT"
bash /cache-scripts/settings.sh
# Newly imported recipes must be reindexed by the final defconfig.
rm -rf tmp/info
rm -f tmp/.packageinfo
