# Audited hostpkg contracts

Unmodified source files downloaded with `gh api ... -H 'Accept: application/vnd.github.raw+json'`:

- `homeproxy.Makefile`: yahuisme/packages, `luci-app-homeproxy/Makefile`, commit `6ff620f4df18eed4321be0778dac03f25909f6ad` (also identical at audited current `bc703dff1c3575613fcfdbddd6a2755da2b6da77`).
- `luci.mk`: immortalwrt/luci, `luci.mk`, commit `830486a7e412a83f233e9c18bd1eb3668212c799`; SHA256 `15d8403c377883f37bc2d87e46c3d41790ba05fab743d14d648a3d7a12327efa`.

The firmware's VIKINGYFY/immortalwrt `feeds.conf.default` selects unbranched immortalwrt/luci. The exact normalized HomeProxy recipe SHA256 is `f409a76551babc4cfdef2b191c74f074d37866545c6eb17681989e1d2cf1d1f2`, replacing only complete decimal `PKG_VERSION:=...` and `PKG_RELEASE:=...` lines with `:=@metadata@`. Other bytes must match.

Audit: HomeProxy declares target dependencies and conffiles, no host build. luci.mk lines 129–131 establish host dependencies independent of payload; lines 200–224 copy payload and compile only when src/Makefile exists; lines 226–255 and 365–395 install/minify/translate target payload, not hostpkg artifacts. Versions affect target metadata/substitution. Preserve complete final config through the unchanged toolchain key. Retain LICENSE, UPSTREAM-TRACKING.md and tests in the full inventory. New top-level inputs disable the optimization, including src and patches. Unknown luci.mk or recipe bytes likewise revert to full hashing.

Historical replay (network-independent test once sources are downloaded):

1. Download `gh api repos/yahuisme/packages/tarball/REF` for each REF below.
2. Extract the `*/luci-app-homeproxy/` members, preserving modes and links, beneath `$HOMEPROXY_AUDIT/REF/`.
3. Run `HOMEPROXY_AUDIT=/path/to/downloads python3 -m unittest Tests.test_hostpkg_cache -v`.

REFs: `ab5769214950488d55d30910cb1321eaec27ac0e` and `6ff620f4df18eed4321be0778dac03f25909f6ad`. The test copies both real package trees into the same physical buildroot and holds luci.mk, bootstrap and toolchain key fixed. Full inventory hashes must differ while optimized keys agree. No full-build performance claim follows from this controlled replay.
