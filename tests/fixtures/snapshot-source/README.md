# Official snapshot source fixture

Unmodified files fetched from official Git objects:

- ImmortalWrt: `4765b657625ec5bbda74b44400465fe043802b30`
- ImmortalWrt LuCI: `319f7c96e3530246cf91cfdd9bacb3fa44dc3a4e`

`source-identity.json` records those exact commits and the separate `apk_assembly_source` revision for `include/{image,rootfs}.mk` and `package/Makefile`. All `feeds/luci/` files are from the LuCI commit; remaining paths come from `source`. This is a historical test reference, not a production source pin. Formal images follow official Snapshot `master`; only the separately downloaded, unmodified HomeWRK RAM image follows the latest official numeric stable release.

The fixture exercises complete settings and native common/per-device APK assembly hooks without compilation. The rootfs-cache regression executes the real upstream GNU make key/eval expressions and the generated snapshot prerequisite with harmless private command boundaries; it checks miss → hit → changed-provenance miss and failure propagation. It does not substitute for signed-APK solver execution, final defconfig, compiled images or router validation.

The separate `../mx4200-native-boot.sh` fixture is the official `package/base-files/files/etc/init.d/boot` at ImmortalWrt `73bc086a62f951d96e5d7404f04c4d73e141cad2`. Tests run only its `uci_apply_defaults` function with private paths and native UCI, not any boot services.
