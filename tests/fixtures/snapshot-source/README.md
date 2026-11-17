# Official snapshot source fixture

Unmodified files fetched from official Git objects:

- ImmortalWrt: `4765b657625ec5bbda74b44400465fe043802b30`
- ImmortalWrt LuCI: `319f7c96e3530246cf91cfdd9bacb3fa44dc3a4e`

`source-identity.json` records those exact commits. All `feeds/luci/` files are from the LuCI commit; other upstream paths are from the main source commit. This is a reviewed historical test reference, not a production source pin: each CI build resolves the latest official numeric stable release once and fetches that exact release tag.

The fixture exercises complete settings and native common/per-device APK assembly hooks without compilation. The rootfs-cache regression executes the real upstream GNU make key/eval expressions and the generated snapshot prerequisite with harmless private command boundaries; it checks miss → hit → changed-provenance miss and failure propagation. It does not substitute for signed-APK solver execution, final defconfig, compiled images or router validation.
