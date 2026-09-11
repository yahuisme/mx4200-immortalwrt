# AI 协力构建的 Linksys MX4200 ImmortalWrt 固件

适用于 **Linksys MX4200v1 / MX4200v2** 路由器的定制 ImmortalWrt 固件构建项目。

基于 [ImmortalWrt 官方](https://github.com/immortalwrt/immortalwrt)最新正式版，集成 [LiBwrt](https://github.com/LiBwrt/LibWrt) NSS 适配与内置 NSS 软件包。

> ⚠️ **仅适用于 Linksys MX4200v1 / MX4200v2，请勿刷入其他型号设备。**

---

## ✨ 主要特性

- 🌐 默认中文 LuCI 界面
- 🎨 默认 Aurora 主题
- 🚀 集成 NSS / ECM 与 ath11k 无线加速
- 📡 集成 802.11s Mesh 与 usteer 漫游辅助
- 🛡️ 内置 HomeProxy 与 sing-box
- ⚡ BBR 拥塞控制与 USB 3.0 存储支持

---

## 🧩 预装应用

HomeProxy 与 sing-box 由专属源 [yahuisme/packages](https://github.com/yahuisme/packages) 维护。

| 插件 | 功能说明 |
| :--- | :--- |
| [`luci-app-homeproxy`](https://github.com/yahuisme/packages/tree/main/luci-app-homeproxy) | 基于 sing-box 的代理管理 |
| `luci-app-advanced-reboot` | 双分区切换与高级重启 |
| `luci-app-usteer` | AP / Mesh 漫游辅助 |
| `luci-app-wol` | 网络唤醒 |
| `luci-app-ttyd` | 网页终端控制台 |
| `luci-app-aurora-config` | Aurora 主题设置 |

---

## 📦 固件下载

前往 [Releases](https://github.com/yahuisme/mx4200-immortalwrt/releases) 下载对应硬件版本的镜像。

| 镜像 | 用途 |
| --- | --- |
| `factory.bin` | 从原厂固件刷入 |
| `sysupgrade.bin` | 已有兼容固件升级 |

每次发布包含 MX4200v1 / MX4200v2 各一份 factory 与 sysupgrade 镜像，共四个文件。刷入前核对机身硬件版本与镜像文件名。

---

## 默认访问

- 管理地址：`192.168.10.1`
- 管理密码：无
- Wi-Fi SSID：`MX4200`
- Wi-Fi 密码：`12345678`

---

## 📡 默认无线配置

| 项目 | 2.4 GHz | 5 GHz 低段 | 5 GHz 高段 |
| --- | --- | --- | --- |
| 状态 | 开启 | **关闭** | 开启 |
| 区域 | US | US | US |
| 信道 | 11 | 48 | 149 |
| 加密 | WPA2-PSK / CCMP | WPA2-PSK / CCMP | WPA2-PSK / CCMP |
| 发射功率 | 23 dBm | 25 dBm | 25 dBm |

---

## 🔄 自动构建

GitHub Actions 每日自动构建，也可手动触发。

```text
MX4200_ImmortalWrt_<正式版标签>_<构建时间>
```

源码适配检查通过后才继续构建。Release 仅发布刷机镜像，源码版本与移植记录保存在 Actions 的 `source-lock` 附件中。

源码适配与验证方法见 [NSS 维护说明](docs/NSS-MIGRATION.md)。
