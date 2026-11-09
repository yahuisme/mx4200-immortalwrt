# Reviewed early bootstrap sources

These locks authorize only the paired `build_dir/host` / `staging_dir/host`
snapshot immediately after `make tools/ccache/compile`, before world. They do
not authorize a world-complete host tree or a cross-toolchain restore.

| Source | Post-customization inventory SHA256 |
| --- | --- |
| OpenWrt `795f369b181cd128962fa8f60a03eaf0ac8afac6` | `04fe4b66fa7d80b01fab7f3a608ce169799c5e107c4c14bd9d21c92c7932acf7` |
| ImmortalWrt `16f34d329992d73900c2fd3d4b3d41b87e8cd234` | `1bef18e2273cc6ba0f0d2f8306a9df8b3fa0d31979ef0e9d8b059ee92ddf5ce3` |

The published ImmortalWrt source `13376a7112809b19d3413a1689a4244c45165003`
has the same complete inventory. Records cover every file under tools/scripts
and all `FIXED_INPUTS`, plus the present `.external-packages.mk`, including
permissions and missing fixed files. Materialize
Git regular/executable modes as 0644/0755: codeload tar headers can carry group
write bits that a Git checkout does not retain. Do not weaken the production
mode hash to accept tar permissions.

## Delta and producer review

The former reviewed OpenWrt `6db25ee835eb55af521125c84b12ffd0495f671b`
and ImmortalWrt `2f97ee0c9fad256d6ffea841f9bfe0415ece3ca9` inventories were
reconstructed and matched their existing hashes. Complete current records differ
at six OpenWrt paths and four ImmortalWrt paths, plus the newly inventoried
`.external-packages.mk`:

- Both: `rules.mk` adds a GCC version fallback in the normal internal-toolchain
  branch. It changes target compiler-version metadata, not host flags/recipes;
  early host producers do not use GCC_VERSION. External/native toolchains remain rejected. `tools/mold/Makefile`
  advances its version and source hash; mold is outside the early ccache closure.
- Both: production `external_packages.prepare()` changes `include/rootfs.mk`
  and `package/Makefile`. The added external make fragment contains only package
  and repository assignments. Its consumers are APK install/cache/snapshot and
  rootfs verification recipes, not early host producers. Because GNU make parses
  this fragment, its content/mode/presence are now explicitly inventoried; an
  injected include or changed assignment cannot inherit the reviewed lock.
  A linked or nonregular fragment is rejected. The snapshot target is
  a prerequisite of package/install, not tools/ccache/compile. The rootfs macros
  and ROOTFS_KEY shell expression are deferred. The actual changed framework
  bytes remain hashed; arbitrary later edits revert to full-toolchain binding.
- ImmortalWrt also drops an obsolete uClibc loader glob inside the deferred
  mklibs rootfs macro.
- OpenWrt: `include/subdir.mk` adds dtbs_check only for target/linux goals;
  `scripts/mkits-qsdk-ipq-image.sh` changes image description basename formatting.
  Neither changes the early host producer closure.

Native GNU make `-rR -qp` evaluation of the actual tools/Makefile, with recipe
expansion/recursive execution disabled, gives the same 16 producers for both:
ccache, cmake, expat, flock, libdeflate, libressl, meson, ninja, patch, pkgconf,
sed, tar, xxhash, xz, zlib and zstd. This includes implicit core/patch dependencies,
not merely tools-y. Its Makefiles, patches, source hashes and scripts are covered
by the inventory. The queried tools file has no parse-time `$(shell ...)`.

The recursive framework was reviewed through rules, toplevel/subdir/prereq,
host-build, depends, download/unpack/quilt, autotools, CMake and Meson. Their
host site inputs are site/cache and site/darwin; helper scripts and tool headers
are locked. Prepared/configured/built/installed stamps still use native rules.
Package/feed recipes can write host staging later, which is why the snapshot
must precede world. Other W1700K customization writes apps, target/package/feed
patches and runtime files, outside this producer inventory. No customization
adds a host producer or edits tools/scripts.

## MX4200 rolling-source review

MX4200 has its own locks, not either W1700K lock:

| Official source | MX post-customization inventory SHA256 |
| --- | --- |
| Stable `4fc16f2985a358bd43bb522e43f05395fcbd6ed5` | `5e09e8d00cbee466260d9391bab5d5f38a41ed7a439e553a9ee49a517deb435f` |
| Master `4765b657625ec5bbda74b44400465fe043802b30` | `a6008400054b94165035f5a07888725ef3505818f63f5ad07db380214de04f4e` |

The stable source was independently rematerialized from its immutable archive
with Git 0644/0755 modes and the historical production mirror filter; all 453
canonical records reproduce the existing stable digest. The current 447 records
come from the complete current `custom.sh` → packages/settings/external-prepare
execution, with package source `001160ae87f45aaa52ac81c39fe16c851a1f72b8` and
LuCI `319f7c96e3530246cf91cfdd9bacb3fa44dc3a4e`. Only shell mount paths and
clone transport were relocated; generated makefile bytes retain production paths.
The four customization-affected locked paths are `.external-packages.mk`,
`include/rootfs.mk`, `package/Makefile` and `scripts/projectsmirrors.json`.

Complete stable/current record comparison identifies 170 changed paths: 24
early-producer records, 19 framework/generated records, five early helper
records, the tools dependency graph, three Rust helper records, 100 later-tool
records and 18 later metadata/image/utility records. These are not exclusions:
every changed/new/deleted file still participates in the exact inventory.

- Early ccache advances 4.12.1 → 4.13.3, CMake 4.2.0 → 4.4.3, Expat
  2.7.3 → 2.9.0, libdeflate 1.25 → 1.26, Meson 1.6.1 → 1.11.2,
  patch 2.8 → 2.8.1, sed 4.9 → 4.10, xz 5.8.1 → 5.8.4 and
  zlib 1.3.1 Git source → 1.3.2 archive. Their recipes, source hashes,
  templates and patch additions/removals are locked, not declared compatible
  with historical artifacts. CMake now supplies the explicit staged zstd
  include/static library and disables tests through configure options.
- `host-build.mk` still owns native prepared/configured/built/installed stamps.
  New hooks record build time, remove host `.la` files via autotools, and enable
  opt-in configure caching for Expat/LibreSSL/patch/sed/tar/xz. The new
  `include/site/cache` is already a fixed input (formerly recorded missing);
  its complete bytes, Darwin base site and host flags remain covered. Default
  configure caches live under disposable `tmp`, not the archived host pair.
  `CONFIGURE_CACHE_DIR` can redirect that new consumer outside the lock, so
  nonempty environment overrides are now rejected, like `CONFIG_SITE`.
  `site/cache:12-13` also sources a readable inherited `CONFIG_SITE_BASE`.
  On Linux, `HOST_CONFIG_SITE_BASE` is empty and `Host/Exports/Default` only
  exports a replacement when nonempty, leaving that inherited path effective.
  Nonempty `CONFIG_SITE_BASE` environment values are therefore rejected too,
  before inventory/key generation; hashing only its path would leave mutable
  external shell contents unlocked. Unset/empty values preserve the normal
  reviewed-independent contract.
- `depends.mk` memoizes recipe hashes and fixes locale ordering; timestamp.pl
  gains fractional timestamps and a find-newer fast path. Download integrity
  memoization uses expected hash plus inode/size/mtime/ctime under disposable
  tmp, and changed download.pl deletes a bad local file before terminating.
  GNU download mirrors are the actual MX-filtered projects JSON. No completion
  stamps are fabricated or touched by this change.
- `rules.mk` memoizes config/CPU/compiler probes, adds configure-cache and build
  logging helpers and target remapping/version helpers. Top-level changes cache
  scans/config checks and build metadata; subdir refactoring adds parallel variant
  dispatch and target-only DT checks. These entire framework files are locked.
  The source-override paths remain rejected; early producer recipes do not opt
  into `HOST_USE_GIT_SRC` or add external `PKG_FILE_DEPENDS`.
- Actual tools-rule GNU make `-rR -qp` evaluation with the retained complete final
  config still yields ccache, cmake, expat, flock, libdeflate, libressl, meson,
  ninja, patch, pkgconf, sed, tar, xxhash, xz, zlib and zstd. The query has an
  empty phony default, no recursive recipes/include remaking, and its tools
  input has no parse-time shell/include calls. Explicit recursive include review
  of these producers closes through rules/debug/verbose, host-build,
  download/unpack/quilt/depends/autotools, CMake and Meson, with locked tools
  headers, templates, site files and helper scripts. Later tool/source metadata,
  image generators and firmware packers are outside this early producer set.
- Rust is a newly selectable tools branch. `tools/rust`, bindgen/cbindgen and
  sccache can read `include/rust-values.mk`/`rust-host-build.mk`, outside this
  early C/C++ lock; corrosion introduces Rust too. Independent reuse therefore
  falls back to full TC binding for all Rust tool/mode selectors, a nonempty
  Rust host path and all-host selection. Even explicit `=n` is nonempty in GNU
  make and conservatively stays bound. No Rust include is whitelisted.
- The generated MX fragment has exactly two package/repository assignments,
  consumed by deferred APK/rootfs macros. The new snapshot prerequisite is on
  package/install, not tools/ccache/compile; rootfs cache shell/eval expansion is
  deferred until that recipe. Its bytes/mode/presence remain locked and linked
  or nonregular forms fail closed. Runtime signed APK indexes are later inputs,
  not bootstrap producers. Package/feed/toolchain host writers run later; the
  snapshot must still be taken before world.

## Acceptance and limits

Run `BOOTSTRAP_SOURCE=/absolute/private/prepared/tree python3 -m unittest
discover -s tests -p test_bootstrap_cache.py -v`. The opt-in tests require the
real reviewed inventory, prove independence from TC_KEY, preserve later kernel,
runtime and external APK index-only changes, and test source/mode/config/builder/
environment invalidation plus unknown-inventory fallback. Full effective config
fingerprinting remains intact; BUILD_ALL_HOST_TOOLS stays toolchain-bound.
The helper self-hash makes this lock update cold for bootstrap only; it does not
change the toolchain key algorithm or inputs.

`BOOTSTRAP_SOURCE` enables the MX real-source CLI mutation matrix;
`MX_PREPARED_SOURCE` also enables its exact MX post-custom control. The CLI
checks content/mode/presence changes to tools, scripts, mirror JSON, host/site,
rootfs/package and generated make inputs; linked/nonregular generated fragments;
complete config/mode/builder/environment changes; every Rust/all-host y/m/n
branch; and external-source/path rejection. Unknown inventories stay TC-bound.
An explicit `CONFIG_SITE_BASE` negative is independent of the implementation's
`OVERRIDES` enumeration; the prepared-source CLI also rejects the real inherited
variable across changed external-file bytes and both TC keys, while empty is a
positive control. Removing only this override guard must fail the regression.
Native tar CLI controls retain script symlinks/nanosecond stamps, reject an empty
executable ccache on restore and never execute restored binaries for health.
Existing workflow/budget/recovery replays retain TC-hit skip, TB stamp recheck,
pre-world packing, 1GB compressed admission, MX exact-key repair and publication
gates. The self-hash deliberately starts a new TB cold generation only:
TC compatibility policy and TC/CC/DL namespaces are unchanged.

The OpenWrt config used for dependency parsing is the failed run's requested
config, not a newly generated final defconfig. Complete tools rule/config branch
review and full-config binding are retained; no local conf was run. ImmortalWrt
and MX4200 parsing use retained final configs. All checks are source/make-parse,
key and native archive fixture evidence. No compiler, configuration generator,
real bootstrap stamp reuse, firmware build, hardware or speed acceptance is
claimed. Rolling unknown inventories continue to bind to TC_KEY until reviewed.

## Prepared-source test usage (current and historical inventories)

The historical review above is not an authorization for a new post-custom
inventory. The opt-in entry points now take an explicit expected contract:

- `BOOTSTRAP_SOURCE` selects the private source for the real CLI mutation and
  source/config/environment boundary matrix.
- `MX_PREPARED_SOURCE` selects the private source for the additional MX
  post-custom inventory/key control.
- `BOOTSTRAP_EXPECT_CONTRACT` applies to both paths. Its default is
  `reviewed-independent`: inventory membership in production `REVIEWED` and
  identical keys across two TC keys are both mandatory. For a current stable or
  other unreviewed prepared inventory, explicitly use `full-toolchain-bound`:
  the inventory must **not** be reviewed, both key generations must succeed,
  and changing only TC_KEY must change the bootstrap key. Unknown expectation
  values fail; the suite never infers or silently downgrades the expectation.

For the current unreviewed stable post-custom source:

```sh
env -u LD_LIBRARY_PATH PYTHONPATH=tests \
  BOOTSTRAP_SOURCE=/absolute/private/stable-post-custom \
  MX_PREPARED_SOURCE=/absolute/private/stable-post-custom \
  BOOTSTRAP_EXPECT_CONTRACT=full-toolchain-bound \
  python3 -m unittest test_bootstrap_cache -v
```

For an exact historically reviewed snapshot post-custom source, use the same
command with `BOOTSTRAP_EXPECT_CONTRACT=reviewed-independent`. Do not add a
production lock or change the expected contract just to accept source drift.
If the two source variables name different trees, both must satisfy the same
explicit expectation, or run them separately.

Present framework inputs retain content/mode/present-to-missing mutations;
absent optional fixed inputs such as stable's `include/site/cache` receive a
missing-to-present mutation followed by restoration to absence. The generated
external make fragment also supports an absent baseline; its linked/directory
negative controls remain mandatory. Required producer files are not made
optional. Every mutation must change the key and stay full-TC-bound; builder,
config, environment, external-path and Rust/all-host controls still execute in
both contracts. Tests do not run make, conf/defconfig or a compiler. A retained
source-only config fixture proves only these key boundaries, not a newly
resolved final configuration, real bootstrap reuse, firmware or hardware.
