# AI 协力构建的 Linksys MX4200 系列 ImmortalWrt 固件

适用于 **Linksys MX4200v1 / MX4200v2** 路由器的定制 ImmortalWrt 固件构建项目。

本项目基于 [VIKINGYFY/immortalwrt](https://github.com/VIKINGYFY/immortalwrt) 构建，并针对 MX4200 系列调整软件包和配置。

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

## 📦 固件镜像

| 镜像 | 用途 |
| --- | --- |
| `factory.bin` | 从原厂固件刷入时使用 |
| `sysupgrade.bin` | 从已有 ImmortalWrt 升级时使用，可保留配置 |

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

GitHub Actions 每日 **香港时间 17:00** 自动构建，每个 Release 仅包含 MX4200v1 / MX4200v2 各自的 `factory.bin` 与 `sysupgrade.bin`。
