# NSS source selection review

## Scope and result

This review changes only `Scripts/Prepare.py`, `Config/nss-policy.json`,
`Tests/test_source.py` and this document. No build, commit, push, workflow edit,
source-tree cleanup or product-default edit was performed.

The original 171-entry NSS boundary beginning at `config/Config-ipq.in` is
restored. Eight subsequently added entries are removed after reading their
complete official/donor diffs. This is a bounded source-preparation baseline,
**not a claim that every one of the historical 171 entries is indispensable**.
NSS 11.4 and Mesh driver/mac80211 patches remain present.

## Eight entries reviewed individually

| Removed donor entry | Observed delta and decision |
| --- | --- |
| `include/netfilter.mk` | Removes `IPT_BUILTIN += $(NF_CONNTRACK6-y)`. This is donor conntrack packaging alignment, not an NSS hook; keep official conntrack definitions. |
| `include/version.mk` | Changes default distribution/manufacturer from ImmortalWrt to LibWrt. Unrelated branding; keep official. |
| `package/kernel/qca-ssdk/patches/0012-suppress-noisy-error-log.patch` | Only patch hunk offsets change (785→762 and 795→772); same patch body. No source-level NSS addition; keep official. |
| `target/linux/qualcommax/Makefile` | Replaces DEFAULT_PACKAGES with donor filesystem tools, LuCI, drivers and many NSS clients. No new build hook; keep official defaults, use explicit profile selections. |
| `target/linux/qualcommax/base-files/etc/init.d/set-irq-affinity` | New global RPS/XPS masks (`f`), RX flow count 8192, socket flow entries 65535. Runtime tuning, not required NSS integration. Exclude. |
| `target/linux/qualcommax/base-files/etc/init.d/smp_affinity` | New configurable EDMA IRQ pinning (cores 1/3), logging and mask helpers. No NSS driver loading; exclude donor tuning. |
| `target/linux/qualcommax/base-files/etc/uci-defaults/15_smp_affinity.sh` | Enables that donor IRQ service by default. Exclude with the service. |
| `target/linux/qualcommax/base-files/etc/uci-defaults/991_set-network.sh` | Rewrites DHCPv6/RA, removes ULA, changes LAN IPv6 assignment and packet steering. Unrelated first-boot network policy; exclude. |

## Executable policy

- Delete both whole-tree ignore lists and the unused whole-delta approval hash.
- Exact `take` inventory is the only donor copy/delete boundary. Everything
  outside it remains official; excluded donor paths are recorded, not copied.
- Each selected path has an enforced SHA-256 of its **edit content** and both
  file modes/existence states. Additions are covered in full, deletions include
  removed content. Symlinks/non-files are rejected. Same allowed filename with
  different NSS content fails before output writes.
- Hash input uses byte-preserving line edits, excludes unchanged context and
  line positions. Common official/donor upstream evolution can pass without
  freezing old commits. A changed NSS edit requires review and policy update;
  do not regenerate hashes blindly to silence a failure.
- Positive `watch_patterns` detect newly introduced NSS patches in the existing
  mac80211 NSS hierarchy, numbered qualcommax integration series, cryptodev NSS
  patches, IPQ807x NSS DTS, and NSS/recycler support headers/sources. Other
  devices' IPQ5018/IPQ6018 NSS DTS are outside this MX4200 boundary.
- Kernel series and exact kernel source metadata must still match. Both sources
  must be clean; CLI checks origin, release tag and remote tag commit.
- Latest official stable metadata and donor `/releases/latest` remain dynamic.
  `review_basis` is historical evidence only, never an acceptance commit pin.
  Recipe source revisions and archive hashes are separate reproducibility data.
- `source-lock.json` retains resolved release/commit/feed provenance and whole
  donor delta fingerprint, and adds policy hash, selected edit hashes, actual
  transplanted file hashes, and excluded-path inventory. VIKING remains an
  integration-method reference, not the source of copied platform defaults.

## Real execution evidence

Clean input repositories:

- `/mnt/mx4200-local-sources/official`, `v25.12.2`,
  `4fc16f2985a358bd43bb522e43f05395fcbd6ed5`
- `/mnt/mx4200-local-sources/libwrt`, `v25.12.2`,
  `0fd5daca26aed9cab74b4141690deb5d997383f1`

The CLI resolved current release metadata and checked remote tags successfully:

```sh
python3 Scripts/Prepare.py --sources /mnt/mx4200-local-sources \
  --output /mnt/mx4200-nss-policy-final-COXLUt
```

Exit 0. Final output is a newly created tree; its adjacent `.prepare.log` and
`source-lock.json` retain evidence. Earlier fresh execution is retained at
`/mnt/mx4200-nss-policy-NLiMZ5`. The old
`/root/mx4200-nss-investigation/verified-core` was read only for historical
provenance, never reused as output or cleaned.

Observed 392 donor differences; 171 selected paths. Verified selected output
bytes/deletions against donor, all eight removed entries against official, and
unchanged official feeds. Both input Git working trees remained clean.

Real selected source files were copied into the separate retained gate-test tree
`/mnt/mx4200-nss-gate-_8p5wfc2`. Mutating the actual ath11k Mesh patch was rejected
as `Unreviewed NSS content`; a new NSS patch path was rejected as `Unreviewed NSS
extension`; an unrelated additional donor path did not block selection.

`python3 -m unittest discover -s Tests -p test_source.py`: 12 tests pass.
Tests include shared upstream context evolution, changed selected content,
missing edits, new NSS patches, mode/symlink rejection and donor-default exclusion.
`git diff --check`: passes. Image tests use explicit fixtures, not built images.

## Limitations and remaining review

- This is source composition, **not** kernel/mac80211 patch application,
  compilation, firmware download verification, successful boot or Mesh runtime
  validation. No firmware images were built.
- No path-based boundary can discover an arbitrarily relocated new NSS dependency
  hidden in an unrelated donor file. The watched extension points detect known
  NSS layout changes; a new release still needs dependency/build validation.
- Edit fingerprints do not prove semantic compatibility after shared upstream
  context changes. They intentionally allow common evolution; kernel matching
  and subsequent real preparation/build tests remain necessary.
- Historical entries retain some wider donor adaptations: ath11k firmware recipe
  replacement, nat46 recipe/patches, iommu patch removal, patch offset refreshes,
  ARM64_CONTPTE, and ramoops memory additions. They were identified from full
  existing-file diffs, but were not newly justified as minimal NSS requirements
  by this source-copy test. Removing/splitting them requires kernel/mac80211
  patch-application and dependency evidence, not another guessed allowlist edit.
- Mesh support is preserved in source; default enablement belongs to the active
  profile. This review does not edit `Config/NSS.txt` or claim Mesh is enabled
  merely because patches exist.
