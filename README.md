# Linksys MX4200 ImmortalWrt

适用于 **Linksys MX4200v1 / MX4200v2**。

基于官方 ImmortalWrt 最新正式版，集成经审核的 LiBwrt NSS 适配及内置 NSS 包。仅支持 x86_64 GitHub Actions 构建，源码版本与差异记录在每次构建的 `source-lock.json`。

> 仅适用于 MX4200v1 / MX4200v2，请勿刷入其他型号。

## 特性

- Aurora LuCI 主题
- NSS 硬件加速与 802.11s Mesh 支持
- BBR、usteer、WOL
- HomeProxy 与 sing-box
- 每日 UTC 06:00 自动构建

## 预装应用

- `luci-app-homeproxy`
- `luci-app-advanced-reboot`
- `luci-app-usteer`
- `luci-app-wol`
- `luci-app-ttyd`

HomeProxy 与 sing-box 来自 [yahuisme/packages](https://github.com/yahuisme/packages)。

## 镜像

- `factory.bin`：从原厂固件刷入
- `sysupgrade.bin`：已有 ImmortalWrt 升级

每次正式 Release 包含 v1/v2 各一份 factory 与 sysupgrade 镜像。

## 默认配置

- 地址：`192.168.10.1`
- 管理密码：无
- Wi-Fi：`MX4200`
- Wi-Fi 密码：`12345678`
- 默认开启 2.4 GHz 与 5.8 GHz，关闭 5.2 GHz

详细源码适配记录见 [docs/NSS-MIGRATION.md](docs/NSS-MIGRATION.md)。
