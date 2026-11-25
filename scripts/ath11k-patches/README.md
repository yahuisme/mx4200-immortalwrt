# ath11k 回移补丁

默认构建为四款正式固件应用以下补丁。不改 Q6、无线内存模式或 RX 环大小；HomeWRK 的 USB 临时启动镜像仍使用未修改的官方 Stable 镜像。

- `990-rxdma-page-frag-24254.patch`：适配 [OpenWrt #24254](https://github.com/openwrt/openwrt/pull/24254) 的逐 RXDMA 环缓存、缓冲对齐及回收。接在 ImmortalWrt 原生 `984` 之后，替换普通 RX 补缓冲路径并涵盖监控状态缓冲。不移植该 PR 的 IRQ 补丁，也不重复关闭中断；保留现有 `951/954` 崩溃恢复路径。适用于排查长时间负载后的可用内存下降，不等于降低空闲占用。
- `991-mesh-amsdu-26866.patch`：保留 [OpenWrt #26866](https://github.com/openwrt/openwrt/pull/26866) 的补丁字节，仅限制 ath11k 在 802.11s 接口上的发端 A-MSDU 聚合，用于排查对 MT7996 的 Mesh 互通，不改变普通 AP 行为。

验证基线：ImmortalWrt `73bc086a62f951d96e5d7404f04c4d73e141cad2`、mac80211 backports `7.2`。补丁按原生顺序接在 47 个官方 ath11k 补丁之后。构建仍跟随官方 `master`；如果 ath11k 补丁链或 mac80211 源版本变化，构建会停止，需先核对上游是否已合入等效修复，再更新或移除本地回移。

实机评估应以同一源码版本的官方配置作对照，分别比较长时间无线流量下的 `MemAvailable`、802.11s 回程的吞吐与重传。
