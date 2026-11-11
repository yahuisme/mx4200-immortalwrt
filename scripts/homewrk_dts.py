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


def mask_comments(source):
    """Hide DTS comments, retaining quoted bytes and source offsets/newlines."""
    masked = list(source)
    index = 0
    quoted = False
    while index < len(source):
        if quoted:
            if source[index] == '\\':
                index += 2
                continue
            if source[index] == '"':
                quoted = False
        elif source[index] == '"':
            quoted = True
        elif source.startswith('//', index) or source.startswith('/*', index):
            if source.startswith('//', index):
                end = source.find('\n', index + 2)
                if end == -1:
                    end = len(source)
            else:
                end = source.find('*/', index + 2)
                if end == -1:
                    raise ValueError('HomeWRK DTS comment unterminated; review MAC protection')
                end += 2
            masked[index:end] = ['\n' if char == '\n' else ' ' for char in source[index:end]]
            index = end
            continue
        index += 1
    if quoted:
        raise ValueError('HomeWRK DTS string unterminated; review MAC protection')
    return ''.join(masked)


def prepare(root):
    paths = [Path(root) / name for name in (
        'target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts',
        'target/linux/qualcommax/dts/ipq8174-homewrk.dts',
    )]
    matches = [path for path in paths if path.exists()]
    if len(matches) != 1:
        raise ValueError('HomeWRK DTS missing or ambiguous; review MAC protection')
    path = matches[0]
    original = source = path.read_text()
    active = mask_comments(source)
    # Stable uses NSS data-plane nodes and does not yet declare HomeWRK MAC cells.
    # Preserve the same factory MAC mapping as the newer official device tree.
    if path == paths[0] and 'mac_address: mac_address {' not in active:
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
        if active.count(partition) != 1 or 'nvmem-cells' in active:
            raise ValueError('HomeWRK stable MAC layout changed; review MAC protection')
        start = active.index(partition)
        source = source[:start] + cell + source[start + len(partition):]
        for port, label, increment in ((2, 'wan', 0), (3, 'lan3', 1), (4, 'lan2', 1), (5, 'lan1', 1)):
            active = mask_comments(source)
            block = (f'&dp{port} {{\n\tstatus = "okay";\n'
                     f'\tphy-handle = <&qca8075_{port - 1}>;\n\tlabel = "{label}";\n')
            if active.count(block) != 1:
                raise ValueError('HomeWRK stable Ethernet layout changed; review MAC protection')
            end = active.index(block) + len(block)
            source = (source[:end] + f'\tnvmem-cells = <&mac_address {increment}>;\n'
                      '\tnvmem-cell-names = "mac-address";\n' + source[end:])
    active = mask_comments(source)
    # Existing cells are not enough: validate the complete factory mapping on
    # repeat preparation and newer layouts before accepting the NAND guard.
    cell_pattern = (r'partition-devinfo\s*\{\s*label = "devinfo";\s*read-only;\s*'
                    r'nvmem-layout\s*\{\s*compatible = "ascii-eq-delim-env";\s*'
                    r'mac_address: mac_address\s*\{\s*compatible = "mac-base";\s*'
                    r'#nvmem-cell-cells = <1>;\s*\};\s*\};\s*\};')
    if len(re.findall(cell_pattern, active)) != 1 or active.count('mac_address: mac_address {') != 1:
        raise ValueError('HomeWRK factory MAC cell changed; review MAC protection')
    prefix = 'dp' if re.search(r'^&dp2 \{', active, re.M) else 'swport'
    for port, label, offset in ((2, 'wan', 0), (3, 'lan3', 1), (4, 'lan2', 1), (5, 'lan1', 1)):
        blocks = re.findall(r'^&' + prefix + str(port) + r' \{([^{}]*)\};', active, re.M)
        if (len(blocks) != 1 or
                blocks[0].count(f'label = "{label}";') != 1 or
                re.findall(r'nvmem-cells\s*=([^;]*);', blocks[0]) != [f' <&mac_address {offset}>'] or
                re.findall(r'nvmem-cell-names\s*=([^;]*);', blocks[0]) != [' "mac-address"']):
            raise ValueError('HomeWRK Ethernet MAC mapping changed; review MAC protection')
    if active.count(ANCHOR) != 1:
        raise ValueError('HomeWRK NAND controller changed; review MAC protection')
    anchor_end = active.index(ANCHOR) + len(ANCHOR)
    tail = active[anchor_end:]
    before_nand = tail.split('\n\tnand@0 {', 1)
    if len(before_nand) != 2:
        raise ValueError('HomeWRK NAND node changed; review MAC protection')
    if 'compatible = "qcom,smem-part";' not in tail:
        raise ValueError('HomeWRK partition layout changed; review MAC protection')
    if 'partitions {' in before_nand[0]:
        if before_nand[0] != mask_comments(GUARD):
            raise ValueError('HomeWRK partition protection changed; review upstream')
    else:
        if before_nand[0] != '':
            raise ValueError('HomeWRK partition layout changed; review MAC protection')
        source = source[:anchor_end] + GUARD + source[anchor_end:]
    if source != original:
        path.write_text(source)


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except (IndexError, OSError, ValueError) as error:
        sys.exit(f'ERROR: {error}')
