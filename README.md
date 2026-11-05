# MX4200 ImmortalWrt

基于 [ImmortalWrt 官方最新 stable release](https://github.com/immortalwrt/immortalwrt/releases)，适用于 Linksys MX4200v1 / MX4200v2。

2026.11.05：新增 MX4300 / HomeWRK 机型固件。

固件下载见 [Releases](https://github.com/yahuisme/mx4200-immortalwrt/releases)，分为 **MX4200** 和 **MX4300 / HomeWRK** 两组独立发布。请选择对应机型及硬件版本的镜像：

| 镜像 | 用途 |
| --- | --- |
| `factory.bin` | MX4200 / MX4300 从原厂固件刷入 |
| `factory.ubi` | HomeWRK 初次安装的 UBI 镜像 |
| `sysupgrade.bin` | 从已有 OpenWrt / ImmortalWrt 升级 |

HomeWRK 初次安装需按[官方设备支持说明](https://github.com/openwrt/openwrt/commit/07f8319d2d9166a41c2fd94ec1422bcd80ada991)使用串口 / U-Boot 与 USB 启动临时系统，不支持套用 MX4300 的原厂网页刷入方式。升级建议不保留配置。

## 功能

- 中文 LuCI 与 Aurora 主题。
- HomeProxy 代理管理界面与 sing-box 核心。
- 设备驱动及基础 USB 支持沿用官方默认。
- 三频 Wi-Fi，默认开启 2.4 GHz 与 5.8 GHz。

## 预装应用

| 插件 | 功能说明 |
| --- | --- |
| [HomeProxy](https://github.com/yahuisme/packages/tree/main/luci-app-homeproxy) | 基于 sing-box 的代理客户端 |
| Aurora 配置 | 主题设置 |
| 高级重启 | 支持机型的双分区重启切换 |
| 网络唤醒 | 唤醒局域网设备 |
| 网页终端 | 浏览器终端访问 |

高级重启仅在 MX4200v1/v2、MX4300 中预装；HomeWRK 不预装，保留系统原生重启。

HomeProxy 与 sing-box 使用 [yahuisme/packages](https://github.com/yahuisme/packages) 的最新源码构建。HomeProxy 默认停用，需自行配置节点或订阅后启用。

Aurora 主题及配置插件使用官方 APK 软件源，每次构建获取源内最新版本，并预置签名公钥与更新源。后续可在 **系统 → 软件包** 刷新列表并更新。

## 默认设置

- 管理地址：`192.168.10.1`
- 管理密码：无
- Wi-Fi 名称：MX4200v1/v2 为 `MX4200`；MX4300 / HomeWRK 为 `MX4300`
- Wi-Fi 密码：`12345678`

| 项目 | 2.4 GHz | 5.2 GHz | 5.8 GHz |
| --- | --- | --- | --- |
| 状态 | 开启 | 关闭 | 开启 |
| 区域 | US | US | US |
| 信道 | 11 | 48 | 149 |
| 加密 | WPA2-PSK | WPA2-PSK | WPA2-PSK |
| 配置功率 | 23 dBm | 25 dBm | 25 dBm |

## 构建

每月 1、4、7……日自动构建，计划时间为香港时间 12:00。

也可手动运行 Actions。使用 Ubuntu 24.04 ARM64 runner 与 Debian ARM64 Docker 环境，一次构建四个机型，各自沿用官方硬件定义与默认依赖。每次发布两组 Release，仅附对应机型的 factory 与 sysupgrade 镜像，每组独立保留最近一版。
