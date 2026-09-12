# MX4200 build optimization evidence

## Observed CI (not the modified workflow)

Full `gh run view --log` captures: runs 34638112282 and 34631085279.
The former has 6485 lines; the latter 6602. Local captures and parsed step
intervals are under `/root/mx4200-run-*.log` and
`/root/mx4200-upstream-evidence/log-analysis.json`.

Run 34638112282 starts bootstrap host compilation at 19:23:14, final Go 1.26
host compilation at 19:37:04, the dummy golang dependency at 19:41:24, and
sing-box immediately afterward. These are start timestamps, not independently
measured package wall times: other packages run concurrently. The important
missing cost in earlier analysis was the bootstrap chain, not just final Go.
Its existing combined download/ccache save step spans about 27 seconds; that
is not a measurement of the new split download save.

## Exact upstream mechanism

Official source: `4fc16f2985a358bd43bb522e43f05395fcbd6ed5` (v25.12.2).
Its feeds.conf.default pins packages to
`84bd86384928955b568988ca0e09e2c78c75173d`.
Prepare.py copies that file; Inputs.py additionally fingerprints consumed local
files and custom package contents. The official feed is not floating here.

At that feed revision, lang/golang/golang-bootstrap builds Go 1.4 -> 1.17 ->
1.20 -> 1.22 -> 1.24.13 when GOLANG_BUILD_BOOTSTRAP=y. Its Config.in explicitly
supports disabling this chain and specifying an external bootstrap root.
Final golang1.26 still builds Go 1.26.8 from checksum-verified source using
that root. The workflow now selects the exact bootstrap version from the
recipe and installs it with setup-go, cache disabled. It does not replace
final host Go or change target firmware packages.

include/host-build.mk uses .prepared*, .configured and .built under
build_dir/hostpkg/go-VERSION, plus staging_dir/hostpkg/stamp/.golang*_installed.
Caching only installed binaries cannot safely skip the build. No blanket
hostpkg cache or fabricated completion stamps were introduced.

## Local execution

- Existing baseline: 36 tests, 1 skipped. Final: 40 tests, 1 skipped.
- actionlint, git diff --check and git fsck --full passed.
- Exact official source + sparse exact feed: make defconfig preserved external
  bootstrap settings. Actual bootstrap host-compile returned Nothing to be done.
- Native final-host recipe dry-run resolved the specified external root and
  both hostpkg build/install stamps. Direct package invocation required
  HOST_OS=Linux, HOST_ARCH=aarch64 and IS_PACKAGE_BUILD=1, normally provided by
  the parent OpenWrt make; the corrected run passed.
- Downloaded official Go 1.24.13 ARM64 archive and Go 1.26.8 source; verified
  SHA256 against Go release metadata and the official feed respectively.
  Ran final source src/make.bash with the recipe's external-bootstrap and PIE
  flags successfully: resulting binary reports go1.26.8 linux/arm64.
  This validates bootstrap compatibility on the local ARM64 host, NOT an
  x86_64 firmware build. The CI runner remains ubuntu-24.04 x86_64.
- Download fingerprint CLI tests cover absent/empty cache, timestamp-only
  changes, same-size content changes, nested Go modules, deletion and rename.
  Snapshot after compilation includes Go modules fetched during the build;
  cold caches are saved even if preexisting workspace content did not change.

## Limits

No commit, push, dispatch, release change or remote cache deletion performed.
No full firmware build or modified-workflow CI timing was performed. NSS,
Mesh and four-image configuration are unchanged. Download saves are now
content-change gated; ccache remains 2G. Remote generation pruning was not
added/executed under the explicit no-remote-cache-deletion constraint, so this
change does not claim a hard repository-wide 10GB retention guarantee.
