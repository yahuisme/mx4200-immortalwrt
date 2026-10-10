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

- 开机完成后，WAN **逻辑接口** up 为蓝色常亮，down / 拨号未成功为红色常亮；仅判断 netifd 接口状态，不代表互联网、DNS 或代理可用。
- 使用原生接口 hotplug，并在开机完成后同步一次；没有常驻进程、ping、轮询或插件。启动与救援灯沿用官方，升级沿用官方绿色闪烁。
- 默认只关注 `wan`，忽略 LAN、Wi-Fi、`wan6` 等其他接口事件。纯 IPv6 或自定义出口可用 `uci set system.@system[0].wan_led_interface='wan6'; uci commit system` 指定一个逻辑接口；不自动合并双栈或多 WAN 状态。
- 不改写原生 LED 配置；发现任一状态灯已有其他活动 trigger 时让出控制。自动规则开启且 trigger 为 `none` 时，蓝灯与红灯亮度由本规则管理，不保留手动固定亮度。需要自行配置常亮/关灯时，先用 `uci set system.@system[0].wan_led='0'; uci commit system` 关闭本规则，再应用原生 LED 设置。全局 `leds_off=1` 同样优先。设置后可重启，或执行 `/etc/init.d/mx4200-led boot` 同步。

## 构建

每日自动构建，也可手动运行 Actions。仅发布两个硬件版本各自的 `factory.bin` 与 `sysupgrade.bin`。

[构建维护](MAINTENANCE.md)
