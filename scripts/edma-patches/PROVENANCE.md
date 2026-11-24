# qca_edma RX memory backport

Apply once in the **formal Snapshot** source tree, after customization and before `make defconfig`:

```sh
python3 /cache-scripts/edma_rx_memory.py "$DK_OPENWRT" > /build-record/edma-rx.json
```

The host equivalent is `python3 scripts/edma_rx_memory.py /path/to/immortalwrt`. The hook takes a source root, not a prepared kernel tree. It changes only `target/linux/qualcommax/files/drivers/net/ethernet/qualcomm/qca_edma.{c,h}`; the native kernel preparation copies that overlay. Do not also install the payload in `patches-6.18/` or call it for the independent RAM boot image.

## Patch chain

The EDMA overlay in [ImmortalWrt Snapshot `6003f6b8`](https://github.com/immortalwrt/immortalwrt/tree/6003f6b8c3278a27712f4fdaaa8d1e5faa2b1f54/target/linux/qualcommax) matches the overlay at the [OpenWrt PR #26732 base `8a6b3a31`](https://github.com/openwrt/openwrt/tree/8a6b3a312a7e7118f231173666d45b03ca0f3de9/target/linux/qualcommax). The local chain contains only:

| Payload | Upstream commit | Backport scope |
| --- | --- | --- |
| `01-rx-buffer-tracking.patch` | [`c4252c61`](https://github.com/openwrt/openwrt/commit/c4252c61fc05b5411c1587b74d899f475693f7b6) | Unmodified. Match returned buffers by DMA address using a per-ring shadow array, with a fallback scan. Two distinct fragments can now share the same `struct page`. |
| `02-drop-split-rx.patch` | [`0f512bbb`](https://github.com/openwrt/openwrt/commit/0f512bbbb48ae436154f66123e722d89053390e5) | Adapted. Drop a whole `EDMA_RXDESC_MORE` run across polls, counting one length error. Advance the run state even if a descriptor does not identify a tracked buffer, without recycling an unowned page. |
| `03-half-page-rx.patch` | [`1698cc24`](https://github.com/openwrt/openwrt/commit/1698cc246e28cf9f68e5ac4131a20b757728fe49) | Adapted. Keep the existing hardware-index refill, coherent descriptor rings and fixed interrupt moderation. Do not import PPE virtual ports, GRO changes or TX changes. |

On the reviewed `qualcommax/ipq807x` target, the 13 IRQs in `ipq8074-ess.dtsi` provide four queue sets. At MTU 1500 there are 512 RX ring entries per queue with 2 KiB fragments, versus 2048 entries with 4 KiB pages before: nominal RX fill-buffer capacity falls from 32 MiB to 4 MiB. These figures exclude descriptors, pool caches and outstanding SKBs, and are not measured RAM savings. The fragment offset is used for the DMA and CPU addresses and SKB head; the pool's device-sync span covers the allowed frame in both halves. When headroom, the maximum frame for the active MTU and shared info no longer fit in a fragment, the driver uses a whole page or compound allocation. The MTU/ring reconfiguration path restores the old pool and sizing on failure. Existing maximum MTU and `ethtool -G` limits are unchanged.

## Source guard and records

The hook recognizes reviewed driver C/header and Kconfig/Makefile patch content, not the checkout's SHA. Unrelated Snapshot updates and Linux 6.18 point releases need not be pinned. The 4 KiB ipq807x layout, enabled EDMA, and known build prerequisites are required. Application runs each payload in order with `patch -f -p1 --fuzz=0`; it discards the staged result on any patch failure or full-output mismatch before replacing the two overlay files.

`edma-rx.json` records `applied`, `already-applied` (the identical reviewed backport is present), or `native` (no local patch applied). It contains input/output driver hashes, the Kbuild-patch hashes, and either the ordered payload names, upstream commit IDs and payload hashes or the native reference. The independent source record identifies the moving Snapshot commit. The checked native references include both the fragment commit and [the complete PR head `71d7a7db`](https://github.com/openwrt/openwrt/tree/71d7a7dbd47d5e0eae1376df78a4a2f3b210b456/target/linux/qualcommax): review covered allocation and DMA/SKB offsets, page recycling, split-run discard, four queues, 512-entry defaults, whole-page jumbo and reconfiguration. Neither reference imports anything into ImmortalWrt on a native match.

A new driver pair, changed build prerequisites or a competing patch/overlay fails closed instead of assuming absorption. Review the complete effective driver and native preparation for a new equivalent implementation; add the verified source fingerprints and an untouched native fixture (or retire the hook when the formal Snapshot no longer needs it). Do not infer equivalence from a commit appearing in history, a few matching constants, or a failed forward patch.

## Source-only checks

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -m unittest discover -s tests -p 'test_edma*.py' -v
```

Requires Python 3 and GNU `patch`; tests use checked-in source and need no network or compiler. The fixtures hold full driver pairs from `6003f6b8`, `1698cc24` and `71d7a7db`, Snapshot target config and a generic-config excerpt, corresponding native 0952/0953 patches, and the two pristine Qualcomm Kbuild inputs. The native references have the same relevant config settings and identical 0952/0953 files. The Kbuild inputs are identical in the declared [Linux 6.18.60](https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.18.60.tar.xz) and [6.18.64](https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.18.64.tar.xz) source archives.

Source preparation was also replayed on the full sources: 687 native patches on ImmortalWrt before and after the overlay change, and 682 on the exact PR head, with no patch fuzz or offsets in the native layers. Keep fixture bytes unchanged during compatibility review; use new reviewed sources for new cases. These checks do not validate firmware compilation, DMA on hardware or network performance.
