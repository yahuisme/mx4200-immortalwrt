# HomeWRK device-tree regression input

`ipq8174-homewrk.dts` is unchanged from ImmortalWrt commit
`4765b657625ec5bbda74b44400465fe043802b30`, path
`target/linux/qualcommax/dts/ipq8174-homewrk.dts`.

`stable-homewrk.dts` is unchanged from official tag `v25.12.2`, commit
`4fc16f2985a358bd43bb522e43f05395fcbd6ed5`, path
`target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts`.
This is test provenance, not a production release pin. Stable uses `dp2`–`dp5`
and lacks the newer HomeWRK factory-MAC cells; the adapter preserves the same
WAN offset 0 / LAN offset 1 mapping as the newer official tree.

The test substitutes only the shared include with minimal node declarations,
compiles a private DT fixture, and replays the first-child traversal/deletion
from QSDK U-Boot `fdt_del_partitions()` and `fdt_node_set_part_info()`:
https://github.com/SpaceExplorationTechnologies/starlink-wifi/blob/1d585ee8909bf7bab4391c0c52d8a9d44137b3bb/qca/src/u-boot-2016/common/fdt_support.c

This proves the DT-node preservation boundary, not router boot or firmware
compilation. No flash writes, persistent boot-environment changes or fixed
partition offsets are used by the fix.
