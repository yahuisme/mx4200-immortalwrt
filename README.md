# AI 协力构建的 Linksys MX4200 系列 ImmortalWrt 固件

适用于 **Linksys MX4200v1 / MX4200v2** 路由器的定制 ImmortalWrt 固件构建项目。

本项目以 [官方 ImmortalWrt](https://github.com/immortalwrt/immortalwrt) 最新正式版为基础，从 [LiBwrt/LibWrt](https://github.com/LiBwrt/LibWrt/releases/latest) 最新正式 Release 提取经过审核的 NSS 差异，而非替换整个平台或改名使用 LiBwrt。

**已采用 VIKING 风格的内置 NSS 包方案**：官方最新正式版基座 + LiBwrt 对应正式版平台/无线补丁 + `package/qca-nss/` 四个兼容包目录，不复制整个第三方固件树。三个核心包采用固定 CodeLinaro Git 版本（无 PKG_HASH，保留上游 PKG_MIRROR_HASH）；firmware 使用 qosmio Release tar.zst + PKG_HASH。移除自建归档门禁，交由 OpenWrt 原生下载和校验；尚未完成固件构建。详见 [源码适配与验证记录](docs/NSS-MIGRATION.md)。

> ⚠️ **仅适用于 Linksys MX4200v1 / MX4200v2，请勿刷入其他型号设备。**

---

## ✨ 主要特性

- 🎨 LuCI 默认主题：Aurora
- 🕐 系统时区：香港（UTC+8）
- 🚀 BBR 拥塞控制默认启用（fq + bbr）
- ⚡ 开源 NSS 硬件加速
- 🔗 内置 HomeProxy 与 sing-box
- 📡 三频 Wi-Fi 默认开启 2.4G 与 5.8 GHz
- 🔄 每日自动构建最新固件

---

## 🧩 预装应用

固件严格保持纯净与高效，内置插件全中文支持，代理组件由专属源 [yahuisme/packages](https://github.com/yahuisme/packages) 定制提供：

| 插件 | 功能说明 |
| :--- | :--- |
| [`luci-app-homeproxy`](https://github.com/yahuisme/packages/tree/main/luci-app-homeproxy) | 定制版代理客户端（集成官方最新 `sing-box` 核心） |
| `luci-app-advanced-reboot` | 高级重启（支持双分区切换与关机） |
| `luci-app-usteer` | 802.11k/v 智能漫游与弱信号剔除 |
| `luci-app-wol` | 网络唤醒（Wake-on-LAN） |
| `luci-app-ttyd` | 网页终端控制台 |

---

## 📦 固件镜像

| 镜像 | 用途 |
| --- | --- |
| `factory.bin` | 从原厂固件刷入时使用 |
| `sysupgrade.bin` | 从已有 ImmortalWrt 升级时使用 |

---

## 默认访问

- 管理地址：`192.168.10.1`
- 管理密码：无
- Wi-Fi SSID：`MX4200`
- Wi-Fi 密码：`12345678`

---

## 📡 默认无线配置

| 项目 | 2.4 GHz | 5.2 GHz | 5.8 GHz |
| --- | --- | --- | --- |
| 状态 | 开启 | **关闭** | 开启 |
| 区域 | US | US | US |
| 信道 | 11 | 48 | 149 |
| 加密 | WPA2-PSK | WPA2-PSK | WPA2-PSK |
| 发射功率 | 23 dBm | 25 dBm | 25 dBm |

---

## 🔄 自动构建

GitHub Actions 保留香港时间每日 14:00 的构建入口，使用 x86_64 `ubuntu-24.04`，缓存 `dl` 和 `.ccache`，不复用跨版本 toolchain/staging。每个 Release 必须恰好包含 MX4200v1 / MX4200v2 各自的 `factory.bin` 与 `sysupgrade.bin`。

每次运行从官方 `.versions.json` 的 `stable_version` 和 LiBwrt `/releases/latest` 解析版本，不固定旧 tag。只有正式版本一致、内核一致、源码差异符合审核策略且核心包来源/归档校验通过才继续。官方 feeds 保留 tag 自带 SHA；核心包采用 VIKING 风格的内置目录，qosmio 提交和文件哈希记录在来源锁，不注入滚动 NSS feed。新版本或来源变化需重新审核，不能保证无人维护地跨大版本迁移。
