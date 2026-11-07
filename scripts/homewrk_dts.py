#!/usr/bin/env python3
"""Keep QSDK U-Boot partition fixups away from HomeWRK's MAC cells."""
from pathlib import Path
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
