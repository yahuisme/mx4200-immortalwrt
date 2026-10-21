# MX4200 ImmortalWrt

基于 [ImmortalWrt 官方 master snapshot](https://github.com/immortalwrt/immortalwrt/tree/master)，适用于 Linksys MX4200v1 / MX4200v2。

固件下载见 [Releases](https://github.com/yahuisme/mx4200-immortalwrt/releases)。请选择对应硬件版本的镜像：

| 镜像 | 用途 |
| --- | --- |
| `factory.bin` | 从原厂固件刷入 |
| `sysupgrade.bin` | 从已有 ImmortalWrt 升级 |

## 功能

- 中文 LuCI 与 Aurora 主题。
- HomeProxy 与官方稳定版 sing-box。
- 设备驱动及基础 USB 支持沿用官方默认。
- 三频 Wi-Fi，默认开启 2.4 GHz 与 5.8 GHz。

## 预装应用

| 插件 | 功能说明 |
| --- | --- |
| [HomeProxy](https://github.com/yahuisme/packages/tree/main/luci-app-homeproxy) | 代理客户端 |
| Aurora 配置 | 主题设置 |
| 高级重启 | 双分区重启切换 |
| 网络唤醒 | 唤醒局域网设备 |
| 网页终端 | 浏览器终端访问 |

## 默认设置

- 管理地址：`192.168.10.1`
- 管理密码：无
- Wi-Fi 名称：`MX4200`
- Wi-Fi 密码：`12345678`

| 项目 | 2.4 GHz | 5.2 GHz | 5.8 GHz |
| --- | --- | --- | --- |
| 状态 | 开启 | 关闭 | 开启 |
| 区域 | US | US | US |
| 信道 | 11 | 48 | 149 |
| 加密 | WPA2-PSK | WPA2-PSK | WPA2-PSK |
| 配置功率 | 23 dBm | 25 dBm | 25 dBm |

## 构建

每日自动构建。

也可手动运行 Actions。使用 Ubuntu 24.04 ARM64 runner 与 Debian ARM64 Docker 环境，仅发布两个硬件版本各自的 `factory.bin` 与 `sysupgrade.bin`，保留最近两版。
