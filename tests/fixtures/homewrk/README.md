# HomeWRK device-tree regression input

`ipq8174-homewrk.dts` is unchanged from ImmortalWrt commit
`4765b657625ec5bbda74b44400465fe043802b30`, path
`target/linux/qualcommax/dts/ipq8174-homewrk.dts`.

The test substitutes only the shared include with minimal node declarations,
compiles a private DT fixture, and replays the first-child traversal/deletion
from QSDK U-Boot `fdt_del_partitions()` and `fdt_node_set_part_info()`:
https://github.com/SpaceExplorationTechnologies/starlink-wifi/blob/1d585ee8909bf7bab4391c0c52d8a9d44137b3bb/qca/src/u-boot-2016/common/fdt_support.c

This proves the DT-node preservation boundary, not router boot or firmware
compilation. No flash writes, persistent boot-environment changes or fixed
partition offsets are used by the fix.
