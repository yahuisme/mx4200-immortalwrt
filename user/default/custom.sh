#!/bin/bash
set -euo pipefail
export WRT_THEME=aurora WRT_SSID=MX4200 WRT_WORD=12345678 WRT_IP=192.168.10.1
# Reject unreviewed sources before mirror, package or provenance writes.
python3 /cache-scripts/external_packages.py preflight "$DK_OPENWRT"
python3 /cache-scripts/homewrk_dts.py "$DK_OPENWRT"
python3 /cache-scripts/temperature.py "$DK_OPENWRT"
# Keep regulatory reads and writes on the same extracted caldata file.
python3 - "$DK_OPENWRT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1]) / 'package/base-files/files/lib/functions/caldata.sh'
text = path.read_text()
old = 'ath11k_remove_regdomain() {\n\tlocal target=$1\n'
new = 'ath11k_remove_regdomain() {\n\tlocal target=${1:-/lib/firmware/$FIRMWARE}\n'
if text.count('ath11k_remove_regdomain() {\n') != 1:
    raise SystemExit('Unsupported ath11k caldata helper boundary')
if text.count(old) == 1:
    path.write_text(text.replace(old, new, 1))
elif text.count(new) != 1:
    raise SystemExit('Unsupported ath11k caldata helper boundary')
PY
# Keep mirror selection and firmware customization independent of the runner.
if [ -f scripts/projectsmirrors.json ]; then
    sed -i '/.cn\//d; /tencent/d; /aliyun/d' scripts/projectsmirrors.json
fi
(cd package && bash /cache-scripts/packages.sh)
bash /cache-scripts/settings.sh
# Newly imported recipes must be reindexed by the final defconfig.
rm -rf tmp/info
rm -f tmp/.packageinfo
