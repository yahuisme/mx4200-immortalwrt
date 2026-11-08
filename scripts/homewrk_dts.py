#!/usr/bin/env python3
"""Keep QSDK U-Boot partition fixups away from HomeWRK's MAC cells."""
from pathlib import Path
import re
import sys

ANCHOR = '&qpic_nand {\n\tstatus = "okay";\n'
GUARD = '''
	/* Absorb the bootloader's legacy partition fixup, preserving NVMEM. */
	partitions {
		status = "disabled";
	};
'''


def prepare(root):
    path = Path(root) / 'target/linux/qualcommax/dts/ipq8174-homewrk.dts'
    source = path.read_text()
    # Validate the factory mapping even when the NAND guard is already present.
    cell_pattern = (r'partition-devinfo\s*\{\s*label = "devinfo";\s*read-only;\s*'
                    r'nvmem-layout\s*\{\s*compatible = "ascii-eq-delim-env";\s*'
                    r'mac_address: mac_address\s*\{\s*compatible = "mac-base";\s*'
                    r'#nvmem-cell-cells = <1>;\s*\};\s*\};\s*\};')
    if len(re.findall(cell_pattern, source)) != 1 or source.count('mac_address: mac_address {') != 1:
        raise ValueError('HomeWRK factory MAC cell changed; review MAC protection')
    for port, label, offset in ((2, 'wan', 0), (3, 'lan3', 1), (4, 'lan2', 1), (5, 'lan1', 1)):
        blocks = re.findall(r'^&swport' + str(port) + r' \{([^{}]*)\};', source, re.M)
        if (len(blocks) != 1 or blocks[0].count(f'label = "{label}";') != 1
                or re.findall(r'nvmem-cells\s*=([^;]*);', blocks[0]) != [f' <&mac_address {offset}>']
                or re.findall(r'nvmem-cell-names\s*=([^;]*);', blocks[0]) != [' "mac-address"']):
            raise ValueError('HomeWRK Ethernet MAC mapping changed; review MAC protection')
    if source.count(ANCHOR) != 1:
        raise ValueError('HomeWRK NAND controller changed; review MAC protection')
    head, tail = source.split(ANCHOR)
    before_nand = tail.split('\n\tnand@0 {', 1)
    if len(before_nand) != 2:
        raise ValueError('HomeWRK NAND node changed; review MAC protection')
    if 'compatible = "qcom,smem-part";' not in tail:
        raise ValueError('HomeWRK partition layout changed; review MAC protection')
    if 'partitions {' in before_nand[0]:
        if before_nand[0] != GUARD:
            raise ValueError('HomeWRK partition protection changed; review upstream')
        return
    if before_nand[0] != '':
        raise ValueError('HomeWRK partition layout changed; review MAC protection')
    path.write_text(head + ANCHOR + GUARD + tail)


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except (IndexError, OSError, ValueError) as error:
        sys.exit(f'ERROR: {error}')
