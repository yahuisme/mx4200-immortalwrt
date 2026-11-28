# ath11k 回移补丁

默认构建为四款正式固件应用以下补丁。不改 Q6、无线内存模式或 RX 环大小；HomeWRK 的 USB 临时启动镜像仍使用未修改的官方 Stable 镜像。

- `990-rxdma-page-frag-24254.patch`：适配 [OpenWrt #24254](https://github.com/openwrt/openwrt/pull/24254) 的逐 RXDMA 环缓存、缓冲对齐及回收。接在 ImmortalWrt 原生 `984` 之后，替换普通 RX 补缓冲路径并涵盖监控状态缓冲。不移植该 PR 的 IRQ 补丁，也不重复关闭中断；保留现有 `951/954` 崩溃恢复路径。适用于排查长时间负载后的可用内存下降，不等于降低空闲占用。
- `991-mesh-amsdu-26866.patch`：保留 [OpenWrt #26866](https://github.com/openwrt/openwrt/pull/26866) 的补丁字节，仅限制 ath11k 在 802.11s 接口上的发端 A-MSDU 聚合，用于排查对 MT7996 的 Mesh 互通，不改变普通 AP 行为。
- `992-unique-sta-addr-25520.patch`：保留 [OpenWrt #25520](https://github.com/openwrt/openwrt/pull/25520) head `70884abbf63c41fea38cce837515cb6aad073c90` 的原始补丁字节（仅改本地文件名）。设置 `NEEDS_UNIQUE_STA_ADDR`，使用已有 mac80211 检查在到达驱动前拒绝同一 radio 跨 BSS 的重复地址，避免重复 peer 创建触发固件 assert。同 radio 跨 BSS 迁移需先清除旧关联；不同 radio 不受此限制。尚未在本项目四机型上实测重复认证或漫游。
- `993-ce-rx-kmalloc-24713.patch`：仅回移 [OpenWrt #24713](https://github.com/openwrt/openwrt/pull/24713) 的 CE 接收缓冲分配，不覆盖 `990` 的普通 RX 和监控路径。使用 kmalloc 以减少共享页片段滞留，保留 RX 内存储备语义，以管道配置的长度执行 DMA 映射、解除映射和接收长度检查。上游实测覆盖的是整份 PR；本项目尚未实测 CE-only 的收益或空闲占用变化。

验证基线：ImmortalWrt `73bc086a62f951d96e5d7404f04c4d73e141cad2`、mac80211 backports `7.2`。补丁按原生顺序接在 47 个官方 ath11k 补丁之后，包 release 从原生 `15` 升至 `18`。构建仍跟随官方 `master`；如果 ath11k 补丁链或 mac80211 源版本变化，构建会停止，需先核对上游是否已合入等效修复，再更新或移除本地回移。

实机评估 `993` 时只切换这块补丁，保持 `990`–`992`、源码和配置相同。在相近开机时间和负载下比较 `MemAvailable`，检查无线初始化、关联、持续流量和固件恢复。Mesh 改动另用 802.11s 回程的吞吐与重传评估。
