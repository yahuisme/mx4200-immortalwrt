# Local optimization recovery validation

Recovery is selective from `079325e` onto the current release/NSS/image workflow,
not a revert. Historical GO-CACHE-VALIDATION.md and HOSTPKG-CACHE-VALIDATION.md
are retained as prior evidence, not claims of newly executed native builds.

## Restored mechanisms

- Exact feed Go bootstrap selection, with final Go still built from source.
- Independent hostpkg schema v2 (feed scan metadata excluded), paired PAX archive.
- Split downloads and compiler caches; content-based download save decision after compile.
- Parallel cold ccache bootstrap, unconditional reset, verbose parallel build with
  current serial diagnostic fallback, consistent 2G cleanup/statistics environment.
- Current release locking, Release.py, image verification/dependencies and NSS
  selection are preserved. Scripts/Cache.py bytes are unchanged. External Go changes
  final config and therefore intentionally invalidates the newly populated toolchain
  key; compatibility is not weakened to manufacture a hit.

## Freshness correction

CacheSelection.py enumerates paginated inventory read-only and selects exact keys
by current ref, runner platform, compatible path-version and creation time. Each
logical tier chooses split or combined independently. The known combined cache
from run 34689396485 is newer than both split tiers and must win. Newer split
contents are moved aside and restored intact, never merged with older combined
files. Failed/missing combined restoration restores the previously available split
tier; save steps remain success-gated. Version constants are the observed native
Linux actions/cache versions for the unchanged path lists; if action compression
or path versions change these constants require review (unknown versions fail cold).

## Capacity limitation

Snapshot `/root/mx4200-log-audit/caches.json`: 14 entries, **9,490,719,303 bytes**,
only **509,280,697 bytes** below the conservative decimal 10GB budget. The latest
combined entry is 1,405,308,482 bytes, latest exact toolchain 1,191,039,934 bytes,
and latest hostpkg entry 288,465,307 bytes. Existing generations remain untouched.
The local 2G ccache limit does not bound remote storage; split migration plus a
new config-dependent toolchain cannot simply coexist within that headroom.
All four saves now use compressed-byte admission and exact-key/current-ref
readback. Denied candidates allow later smaller tiers; an unverified attempted
upload blocks subsequent saves, not firmware publication. Native cache measurement
adds a compression pass to preserve existing cache identities; its CI overhead is
not yet measured. This non-destructive gate is not a retention policy: old entries
must be separately reviewed and deletion authorized to restore population headroom.
No remote cache deletion, commit, push or workflow dispatch was performed.

## Local tests

Tests execute complete shell blocks for cold/warm ccache, bootstrap failure,
parallel failure/serial recovery, final failure and statistics failure; migration
fixtures cover all hit combinations, tier freshness, no-merge replacement and
failed/missing restore recovery. Download fingerprints cover same-size edits,
mtime-only changes, rename/delete and compile-time Go module additions.
These are offline behavioral tests, not measured x86 NSS compilation or a promise
of an optimal build duration. Full-suite results should be rerun after concurrent
menu/admission work finishes; optional real-image/NSS tests need external fixtures.
