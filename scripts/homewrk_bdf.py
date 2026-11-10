#!/usr/bin/env python3
"""Share MX4300's native BDF package and v1 selector with HomeWRK."""
from pathlib import Path
import re
import sys


def prepare(root):
    root = Path(root)
    dts = root / 'target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts'
    image = root / 'target/linux/qualcommax/image/ipq807x.mk'
    source, profiles = dts.read_text(), image.read_text()
    old = 'qcom,ath11k-calibration-variant = "Linksys-HomeWRK";'
    new = 'qcom,ath11k-calibration-variant = "Linksys-MX4200v1";'
    variants = re.findall(r'qcom,(?:ath11k-)?calibration-variant\s*=', source)
    if len(variants) != 1 or source.count(old) + source.count(new) != 1:
        raise ValueError('Unsupported HomeWRK calibration selector')
    blocks = re.findall(r'^define Device/linksys_homewrk\n.*?^endef\n', profiles, re.M | re.S)
    donor = re.findall(r'^define Device/linksys_mx4x00\n.*?^endef\n', profiles, re.M | re.S)
    if len(blocks) != 1 or len(donor) != 1 or '\tDEVICE_PACKAGES += ipq-wifi-linksys_mx4200\n' not in donor[0]:
        raise ValueError('Unsupported Linksys BDF package profiles')
    old_package = '\tDEVICE_PACKAGES += kmod-leds-pca963x ipq-wifi-linksys_homewrk\n'
    new_package = '\tDEVICE_PACKAGES += kmod-leds-pca963x ipq-wifi-linksys_mx4200\n'
    block = blocks[0]
    if (block.count(old_package) + block.count(new_package) != 1 or
            len(re.findall(r'\bipq-wifi-\S+', block)) != 1):
        raise ValueError('Unsupported HomeWRK BDF package selection')
    # Validate both consumers before writing either; keep all other model data.
    updated = source.replace(old, new)
    replaced = profiles.replace(block, block.replace(old_package, new_package), 1)
    if updated != source:
        dts.write_text(updated)
    if replaced != profiles:
        image.write_text(replaced)


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except (IndexError, OSError, ValueError) as error:
        sys.exit(f'ERROR: {error}')
