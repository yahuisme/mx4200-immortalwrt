# MX4200 ImmortalWrt

每次构建跟随 [ImmortalWrt 官方 Snapshot 源码](https://github.com/immortalwrt/immortalwrt/tree/master)，支持 Linksys MX4200v1、MX4200v2、MX4300 和 HomeWRK。

正式固件临时回移植 [qca_edma RX 缓冲优化](https://github.com/openwrt/openwrt/commit/1698cc246e28cf9f68e5ac4131a20b757728fe49)：保留四个收包队列，标准 MTU 下 RX 缓冲的理论占用从约 32 MiB 降至约 4 MiB。ImmortalWrt 合入等效实现后不再叠加本地补丁。

## 固件下载

前往 [Releases](https://github.com/yahuisme/mx4200-immortalwrt/releases)，选择对应发布组：

- **MX4200**：MX4200v1、MX4200v2
- **MX4300**：MX4300、HomeWRK

按机型和硬件版本选择镜像，不可混刷。

| 文件名后缀 | 用途 |
| --- | --- |
| `factory.bin` | MX4200v1/v2、MX4300 从原厂后台刷入 |
| `factory.ubi` | HomeWRK 命令行写入，按下方教程安装无需下载 |
| `sysupgrade.bin` | 固件升级；也用于 HomeWRK 从临时系统安装正式固件 |
| `initramfs-uImage.itb` | HomeWRK 从 U 盘启动的临时系统，不写入闪存 |

HomeWRK 临时镜像使用同一份 Snapshot 源码独立构建，保留上游默认设置，加入中文 LuCI。U 盘启动后访问 `192.168.1.1`，可直接在网页升级正式固件。

**首次安装：[Linksys 刷机教程](linksys-first-flash.md)。MX4200v1/v2、MX4300 从原厂后台刷入 `factory.bin`，再用 `sysupgrade.bin` 升级；HomeWRK 拆机连接 TTL，通过 U 盘启动 `initramfs-uImage.itb`，再经 LuCI 后台升级 `sysupgrade.bin`。**

## 功能与应用

预装中文 LuCI、Aurora 主题和以下应用：

| 应用 | 功能 |
| --- | --- |
| [HomeProxy](https://github.com/yahuisme/packages/tree/main/luci-app-homeproxy) | 基于 sing-box 的代理客户端 |
| Aurora 配置 | 主题设置 |
| 高级重启 | MX4200v1/v2、MX4300 支持双分区切换，HomeWRK 不支持 |
| CPU 性能 | 调节 CPU 调频策略 |
| 网络唤醒 | 唤醒局域网设备 |
| 网页终端 | 浏览器终端访问 |

HomeProxy 和 sing-box 从 [yahuisme/packages](https://github.com/yahuisme/packages) 的 `main` 分支构建。HomeProxy 默认未配置节点，使用前需添加节点或导入订阅，并选用节点。

Aurora 主题和配置插件使用 [Aurora 项目的签名 APK](https://github.com/eamonxg/luci-theme-aurora)，可在 **系统 → 软件包** 刷新列表并更新。

## 默认设置

以下设置在首次安装或不保留配置升级后生效。

- 管理地址：`192.168.10.1`
- 登录：`root`，初始密码留空
- Wi-Fi 名称：MX4200v1/v2 为 `MX4200`；MX4300、HomeWRK 为 `MX4300`
- Wi-Fi 密码：`12345678`

| 项目 | 2.4 GHz | 5 GHz 低段 | 5 GHz 高段 |
| --- | --- | --- | --- |
| 状态 | 开启 | 关闭 | 开启 |
| 信道 | 11 | 48 | 149 |
| 配置功率 | 23 dBm | 25 dBm | 25 dBm |

三个频段均使用 `US` 区域和 WPA2-PSK（CCMP）。

## 构建与发布

每天香港时间 00:00 自动构建，也可手动运行 [Actions](https://github.com/yahuisme/mx4200-immortalwrt/actions/workflows/MX4200.yml)。每次构建四个机型，按 MX4200、MX4300 两组发布，每组保留最近一期构建。
