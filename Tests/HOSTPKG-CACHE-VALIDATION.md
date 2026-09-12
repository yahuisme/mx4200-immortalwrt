# Hostpkg cache validation

Local candidate only; no push, dispatch or remote cache deletion.

## Compatibility / payload

`Scripts/Cache.py` remains byte-identical. The independent exact
`mx4200-hostpkg-v1-` key chains the existing toolchain key (final `.config`,
core recipes, platform/kernel headers, host package versions, runner image,
architecture and absolute build root), complete prepared `package` + `feeds`
source content/modes/link targets, and actual external GOROOT content/path.
All package/feed recipe files get deterministic source mtimes; no completion
stamp is touched. Unknown external source symlinks fail closed. There is no
hostpkg restore fallback or merge with legacy staging.

Payload is exactly `build_dir/hostpkg` and `staging_dir/hostpkg`, including
installed libraries/tools, prepared/configured/built/installed stamps and
objects. Package ownership is not tracked comprehensively enough upstream to
safely prune individual staging files. Neither target staging/build output,
tmp metadata, dl nor ccache is included. PAX tar preserves nanosecond mtimes;
actions/cache receives a single precompressed zstd archive.

This conservatively invalidates hostpkg when unrelated feed recipes change;
that is preferable to an unproven partial recursive dependency projection.
The old exact toolchain cache is not invalidated by those feed changes.

## Real execution evidence

Source checkout `/root/mx4200-hostpkg-validation`, upstream core
`4fc16f2985a358bd43bb522e43f05395fcbd6ed5`.
Local machine is **aarch64**; production remains ubuntu-24.04 **x86 NSS**.
These are actual official package recipes, not synthetic stamps:

* libunistring 1.4.2: cold whole make 134.619s; delete both artifact trees,
  recreate source mtimes, normalize, restore PAX archive, warm whole make
  4.415s / host recipe 0.26s. Built and installed stamps remain exactly
  `1789192518655759139` ns. Compressed pair: 7,741,565 bytes.
* Go 1.26.8: actual final official host source build, recipe wall 140.11s;
  pair archive/delete/restore/warm make 4.719s, both completion stamps remain
  `1789192919292211702` ns. Restored executable reports
  `go version go1.26.8 linux/arm64`. Go + libunistring pair: 170,093,375 bytes.
* Recipe content mutation rejected the preceding exact key. Source mtime-only
  mutation did not; feed shared-recipe, mode, host/bootstrap changes tested.
* Partial local feeds produce unrelated missing optional feed warnings during
  metadata scanning. Both real host targets completed successfully.
* Full suite: 47 tests, 1 pre-existing optional prepared-source ABI test skipped;
  actionlint and git diff --check pass.

Evidence scripts/logs/results:
`/root/mx4200-hostpkg-roundtrip.py`, `-roundtrip.json`, `-cold.log`, `-warm.log`;
`/root/mx4200-hostpkg-go-roundtrip.py`, `-go-roundtrip.json`, `-go-cold.log`,
`-go-warm.log`; `/root/mx4200-hostpkg-tests.log`.

No measured claim for full x86 firmware warm savings or full gettext roundtrip.
Parallel package durations must not be added together.

## Capacity / governance handoff

Read-only inventory `/root/mx4200-hostpkg-inventory.json`: six entries total
5,157,447,536 bytes. Latest remote run measured uncompressed hostpkg staging
350MiB and build 798MiB; exact full x86 compressed pair remains to be measured.
The partial native pair size must not be substituted for that measurement.

Hostpkg admission runs **after** other cache saves; it sums every paginated
entry, all generations/refs/legacy/unrelated families, actual compressed
candidate plus max(16MiB, 1%) wrapper reserve, against conservative decimal
10,000,000,000 bytes. A full or unavailable inventory never authorizes upload;
no old cache is deleted to make room. Existing workflow concurrency serializes
MX4200 runs, not independent external cache writers.

This guards the **new hostpkg upload**, not the repository's existing rolling
ccache/download/toolchain upload policies. Parent governance review must
integrate consistent admission and verified-new-save-before-old-generation
retention for those tiers. Keep latest usable same-family/ref cache; prune old
same-family generations only after a nonempty replacement is confirmed by
readback. Do not pre-delete, silently increase paid storage, or claim this
local candidate already enforces repository-wide retention. Interface at
`/root/mx4200-hostpkg-interface.md`. No deletion is authorized in this task.
