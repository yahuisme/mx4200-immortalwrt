# MX4200 ImmortalWrt

基于 [ImmortalWrt 官方最新稳定 Release 源码](https://github.com/immortalwrt/immortalwrt/releases)，适用于 Linksys MX4200v1 / MX4200v2。

2026.11.05：新增 Linksys MX4300 / HomeWRK 机型固件。

## 固件下载

前往 [Releases](https://github.com/yahuisme/mx4200-immortalwrt/releases)，选择对应发布组：

- **MX4200**：MX4200v1 / MX4200v2。
- **MX4300**：MX4300 / HomeWRK。

请选择对应机型及硬件版本的镜像，不可混刷。

| 镜像 | 用途 |
| --- | --- |
| `factory.bin` | MX4200 / MX4300 从原厂固件刷入 |
| `factory.ubi` | HomeWRK 命令行写入用，本教程无需使用 |
| `sysupgrade.bin` | 系统升级；HomeWRK 从临时系统首次安装 |
| `initramfs-uImage.itb` | HomeWRK 从 USB 启动的临时系统，自带 LuCI |

MX4300 发布组附带 HomeWRK 官方最新稳定版临时镜像，自带 LuCI，管理地址为 `192.168.1.1`。每次构建自动下载并校验大小与 SHA-256，保持官方原版不变。

**首次安装：[Linksys 刷机教程](linksys-first-flash.md)。MX4200 / MX4300 网页刷入，HomeWRK 使用 TTL＋U 盘。**

## 功能与应用

- 中文 LuCI 与 Aurora 主题。
- 设备驱动及基础 USB 支持沿用各机型官方默认。
- 三频 Wi-Fi，默认开启 2.4 GHz 与 5.8 GHz。

| 应用 | 功能 |
| --- | --- |
| [HomeProxy](https://github.com/yahuisme/packages/tree/main/luci-app-homeproxy) | 基于 sing-box 的代理客户端 |
| Aurora 配置 | 主题设置 |
| 高级重启 | MX4200v1/v2、MX4300 双分区重启切换，HomeWRK 不预装 |
| CPU 性能 | 调节 CPU 调频策略 |
| 网络唤醒 | 唤醒局域网设备 |
| 网页终端 | 浏览器终端访问 |

HomeProxy 与 sing-box 使用 [yahuisme/packages](https://github.com/yahuisme/packages) 的最新源码构建。HomeProxy 默认停用，需自行配置节点或订阅后启用。

Aurora 主题及配置插件通过官方签名 APK 软件源预装，可在 **系统 → 软件包** 刷新列表并更新。

## 默认设置

以下设置在首次启动或不保留配置升级时生效。

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

## 构建与发布

每日自动构建，计划时间为香港时间 12:00；也可手动运行 [Actions](https://github.com/yahuisme/mx4200-immortalwrt/actions/workflows/MX4200.yml)。

每次构建自动选择官方最新稳定 Release 源码，不固定版本，版本显示沿用官方。使用 Ubuntu 24.04 ARM64 与 Debian Docker 环境，一次构建四个机型，按 MX4200、MX4300 两组发布，每组保留最新一版。
