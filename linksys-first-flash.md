# Linksys 首次刷机教程

安装本仓库的 ImmortalWrt 固件，按机型选择路线：

- **MX4200v1 / v2、MX4300**：原厂后台刷入，再升级一次。
- **HomeWRK**：TTL＋U 盘启动临时系统，再通过网页安装。

> 固件必须匹配机型，MX4200 需区分 v1 / v2。刷写期间不要断电，校验失败时不要强刷。

部分 HomeWRK 标签设备实际已配置为 MX4300。先按[机型辨识说明](https://openwrt.org/toh/linksys/mx4300#before_installation)确认，不能只看外壳标签；无法确认时不要刷写。

## 1. 下载固件

前往 [Releases](https://github.com/yahuisme/mx4200-immortalwrt/releases)，下载对应机型文件。

### MX4200 / MX4300

- MX4200v1 / v2：进入 **MX4200** 发布组，区分硬件版本。
- MX4300：进入 **MX4300** 发布组。

按机型下载两个文件：

- `squashfs-factory.bin`：原厂后台首次刷入。
- `squashfs-sysupgrade.bin`：进入新系统后再升级一次。

### HomeWRK

进入 **MX4300** 发布组，下载文件名含 `linksys_homewrk` 的两个文件：

- `initramfs-uImage.itb`：USB 启动临时系统，自带 LuCI，管理地址 `192.168.1.1`。
- `squashfs-sysupgrade.bin`：安装正式固件。

本教程不使用 `factory.ubi`，无需下载。

## 2. MX4200 / MX4300 安装

### 原厂后台刷入

1. 电脑用网线连接路由器 LAN 口。
2. 关闭电脑 Wi-Fi，有线网卡设为自动获取 IP 和 DNS。
3. 打开原厂后台，通常为 `192.168.1.1`；打不开时查看有线网卡的默认网关。
4. 登录管理员账号，点击页面底部 **CA**，进入 **Connectivity / 连接**。
5. 上传对应机型的 `squashfs-factory.bin`，点击 **Start / 开始**，等待更新并重启。

找不到上传入口时，访问 `https://路由器IP/fwupdate.html`。

### 新系统再升级一次

1. 等待电脑重新获取 IP，打开 `192.168.10.1`。
2. 用户名 `root`，初始密码留空。
3. 进入 **系统 → 备份 / 升级 → 刷写新的固件**。
4. 上传对应机型的 `squashfs-sysupgrade.bin`。
5. **取消勾选“保留配置”**；若有“升级当前分区”，也不要勾选。
6. 校验通过后开始升级，等待重启。

这次升级会覆盖另一分区的原厂系统，使两个分区都安装新系统，无需 SSH 或手动补刷。

完成后跳到“登录与日常升级”。

## 3. HomeWRK 安装

### 准备工具

- Windows 电脑、网线、可清空的 U 盘。
- 3.3V USB-TTL 及 Windows 驱动。
- [PuTTY 中文版](https://github.com/larryli/putty)：从项目 Releases 下载。
- [Rufus](https://rufus.ie/zh/)：下载官方便携版。
- 第 1 节下载的 HomeWRK 两个镜像。

### 制作启动 U 盘

1. 在资源管理器开启“文件扩展名”，将临时镜像重命名为 `initramfs.img`。
2. 插入 U 盘，以管理员身份打开 Rufus。
3. 在“设备”中选择 U 盘，核对型号和容量。
4. 按 **Alt＋M**，启用“忽略启动标记”检查。
5. 点击“选择”，打开 `initramfs.img`，再点击“开始”。
6. 若提示写入方式，选择 **DD 镜像模式**，确认清空并等待完成。

> 会清空整个 U 盘，不能选电脑硬盘。写完后 Windows 若提示格式化，点取消。

镜像不解压、不转换，不选 ISO 模式；无需提前格式化或手动分区，也不是把文件复制进 U 盘。

### 接线与串口设置

路由器断电后接线。白色六针串口插座从左到右，前四针如下：

```text
从左到右：  第1针   第2针   第3针   第4针
路由器：    GND     TX      空      RX
TTL 接线：  GND     RX      不接    TX
```

**只接这三根线，其余针脚不接。不接 VCC，不能使用 5V TTL 或 RS-232。**

插入 USB-TTL，在 Windows「设备管理器 → 端口」查看 COM 号，设置 PuTTY：

```text
连接类型：串口（Serial）
串口：实际 COM 号，例如 COM3
速度：115200
数据位：8
停止位：1
校验：无（None）
流控：无（None）
```

### 启动临时系统

1. 打开 PuTTY 串口，将 U 盘插入路由器。
2. 用路由器原装电源通电。
3. 看到 `Hit any key to stop autoboot` 时按键，中断启动。
4. 在 **U-Boot 命令行**执行：

```text
usb start && usbboot 44000000 0 && bootm 44000000
```

等待临时系统启动。读取或启动失败时停止，不继续刷写。

此时系统只运行在内存中，尚未写入闪存。后续操作均在网页完成，无需继续使用 TTL。

### 网页安装正式固件

1. 电脑用网线连接 HomeWRK 的 LAN 口。
2. 关闭电脑 Wi-Fi，有线网卡设为自动获取 IP 和 DNS。
3. 打开 `192.168.1.1`，用户名 `root`，初始密码留空。
4. 进入 **系统 → 备份 / 升级 → 刷写新的固件**。
5. 上传 **HomeWRK** 的 `squashfs-sysupgrade.bin`，**取消勾选“保留配置”**。
6. 校验通过后开始刷写，等待重启，期间不断电、不拔 U 盘。
7. 完成后移除 U 盘，等待电脑重新获取 IP。

## 4. 登录与日常升级

正式系统管理地址：`192.168.10.1`

- 用户名：`root`
- 初始密码：留空

登录后设置管理员密码和 Wi-Fi 密码，其他默认设置见 [README](README.md#默认设置)。

以后升级：

1. 进入 **系统 → 备份 / 升级**。
2. 上传对应机型的 `sysupgrade.bin`，建议不保留配置。
3. 校验通过后升级，等待重启。

无需重新刷 factory，也无需再次启动临时系统。

## 参考

HomeWRK 临时镜像为 ImmortalWrt 官方最新稳定 Release 原版，随构建获取并核对大小及 SHA-256，不修改系统或默认配置。

- [OpenWrt：MX4200 v1 / v2](https://openwrt.org/toh/linksys/mx4200_v1_and_v2)
- [OpenWrt：MX4300](https://openwrt.org/toh/linksys/mx4300)
- [HomeWRK 上游安装说明](https://github.com/openwrt/openwrt/commit/07f8319d2d9166a41c2fd94ec1422bcd80ada991)
