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

## 状态灯

- 两个硬件版本均使用「系统 → LED 配置」原生规则：蓝灯采用 `netdev` 的 `link` 模式（v1 亮度 255、v2 亮度 51），只跟随设备链路，不随收发流量闪烁；红灯和绿灯默认关闭。
- 首次初始化按当时 `network.wan` 配置绑定设备：PPPoE 使用 `pppoe-wan`，DHCP/static 使用实际 `device`，不假定 MX4200 使用 PPPoE。协议未知或设备缺失时不生成/替换蓝灯规则。之后更改 WAN 协议或设备，请在「系统 → LED 配置」手动调整蓝灯设备。
- 首次初始化补齐缺失规则，并将未修改的官方 `led_blue` 常亮预设替换为上述链路预设；保留配置升级不改设置，用户修改、改名及匿名规则保留。脚本由原生 uci-defaults 执行一次后删除。
- `link` 仅表示所选设备链路状态，不判断 DNS、代理或互联网可达性，也不实现断线自动红灯。没有额外 hotplug、daemon、init 或 upgrade 脚本；启动、救援及升级诊断仍由官方实现负责，保留官方绿色升级指示。
- 官方内核配置已内建 `CONFIG_LEDS_TRIGGER_NETDEV=y`，无需额外 `kmod-ledtrig-netdev` 包。

## 构建

每日自动构建，也可手动运行 Actions。仅发布两个硬件版本各自的 `factory.bin` 与 `sysupgrade.bin`。

[构建维护](MAINTENANCE.md)
