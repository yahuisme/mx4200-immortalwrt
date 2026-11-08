# Official snapshot source fixture

Unmodified files fetched from official Git objects:

- ImmortalWrt: `4765b657625ec5bbda74b44400465fe043802b30`
- ImmortalWrt LuCI: `319f7c96e3530246cf91cfdd9bacb3fa44dc3a4e`

`source-identity.json` records those exact commits. All `feeds/luci/` files are from the LuCI commit; other upstream paths are from the main source commit. This is a historical snapshot test reference, not a production source pin: CI resolves the newest official numeric stable Release on every build.

The fixture exercises complete settings without compilation. The APK unit-test helper converts its assembly files to the reviewed stable direct-install shape; set `MX_APK_SOURCE_FIXTURE` to untouched files from the selected official stable source for exact assembly evidence. The direct-install regression executes the signed-refresh/add recipe lines with harmless private command boundaries and checks that refresh failure blocks installation. It does not substitute for signed-APK solver execution, final defconfig, compiled images or router validation.
