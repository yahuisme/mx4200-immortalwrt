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
    paths = [Path(root) / name for name in (
        'target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts',
        'target/linux/qualcommax/dts/ipq8174-homewrk.dts',
    )]
    matches = [path for path in paths if path.exists()]
    if len(matches) != 1:
        raise ValueError('HomeWRK DTS missing or ambiguous; review MAC protection')
    path = matches[0]
    source = path.read_text()
    # Stable uses NSS data-plane nodes and does not yet declare HomeWRK MAC cells.
    # Preserve the same factory MAC mapping as the newer official device tree.
    if path == paths[0] and 'mac_address: mac_address {' not in source:
        partition = '\t\tpartitions {\n\t\t\tcompatible = "qcom,smem-part";\n\t\t};'
        cell = '''\t\tpartitions {
\t\t\tcompatible = "qcom,smem-part";

\t\t\tpartition-devinfo {
\t\t\t\tlabel = "devinfo";
\t\t\t\tread-only;

\t\t\t\tnvmem-layout {
\t\t\t\t\tcompatible = "ascii-eq-delim-env";

\t\t\t\t\tmac_address: mac_address {
\t\t\t\t\t\tcompatible = "mac-base";
\t\t\t\t\t\t#nvmem-cell-cells = <1>;
\t\t\t\t\t};
\t\t\t\t};
\t\t\t};
\t\t};'''
        if source.count(partition) != 1 or 'nvmem-cells' in source:
            raise ValueError('HomeWRK stable MAC layout changed; review MAC protection')
        source = source.replace(partition, cell, 1)
        for port, label, increment in ((2, 'wan', 0), (3, 'lan3', 1), (4, 'lan2', 1), (5, 'lan1', 1)):
            block = (f'&dp{port} {{\n\tstatus = "okay";\n'
                     f'\tphy-handle = <&qca8075_{port - 1}>;\n\tlabel = "{label}";\n')
            if source.count(block) != 1:
                raise ValueError('HomeWRK stable Ethernet layout changed; review MAC protection')
            source = source.replace(block, block + f'\tnvmem-cells = <&mac_address {increment}>;\n'
                                    '\tnvmem-cell-names = "mac-address";\n', 1)
    # Existing cells are not enough: validate the complete factory mapping on
    # repeat preparation and newer layouts before accepting the NAND guard.
    cell_pattern = (r'partition-devinfo\s*\{\s*label = "devinfo";\s*read-only;\s*'
                    r'nvmem-layout\s*\{\s*compatible = "ascii-eq-delim-env";\s*'
                    r'mac_address: mac_address\s*\{\s*compatible = "mac-base";\s*'
                    r'#nvmem-cell-cells = <1>;\s*\};\s*\};\s*\};')
    if len(re.findall(cell_pattern, source)) != 1 or source.count('mac_address: mac_address {') != 1:
        raise ValueError('HomeWRK factory MAC cell changed; review MAC protection')
    prefix = 'dp' if re.search(r'^&dp2 \{', source, re.M) else 'swport'
    for port, label, offset in ((2, 'wan', 0), (3, 'lan3', 1), (4, 'lan2', 1), (5, 'lan1', 1)):
        blocks = re.findall(r'^&' + prefix + str(port) + r' \{([^{}]*)\};', source, re.M)
        if (len(blocks) != 1 or
                blocks[0].count(f'label = "{label}";') != 1 or
                re.findall(r'nvmem-cells\s*=([^;]*);', blocks[0]) != [f' <&mac_address {offset}>'] or
                re.findall(r'nvmem-cell-names\s*=([^;]*);', blocks[0]) != [' "mac-address"']):
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
        if source != path.read_text():
            path.write_text(source)
        return
    if before_nand[0] != '':
        raise ValueError('HomeWRK partition layout changed; review MAC protection')
    path.write_text(head + ANCHOR + GUARD + tail)


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except (IndexError, OSError, ValueError) as error:
        sys.exit(f'ERROR: {error}')
