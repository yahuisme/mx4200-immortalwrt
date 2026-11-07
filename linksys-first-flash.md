# Linksys 首次刷机教程

适用于 MX4200v1、MX4200v2、MX4300 和 HomeWRK，安装本仓库的 ImmortalWrt 固件。

- **MX4200 / MX4300：原厂后台刷入，步骤相同。**
- **HomeWRK：Windows 电脑接 TTL，启动临时系统后在网页刷入。**

刷机前备份需要保留的配置，刷写期间不要断电。**固件必须匹配机型，MX4200 还要区分 v1 / v2，不可混刷。** 部分带 HomeWRK 标签的机器实际已配置为 MX4300，先按[机型辨识说明](https://openwrt.org/toh/linksys/mx4300#before_installation)确认实际机型，不能只看外壳标签；无法确认时不要继续刷写。

## 一、下载固件

前往本项目 [Releases](https://github.com/yahuisme/mx4200-immortalwrt/releases)：

**MX4200 发布组：**

选择本机 v1 / v2 的 `squashfs-factory.bin` 和 `squashfs-sysupgrade.bin`。

**MX4300-HomeWRK 发布组：**

MX4300 下载本机型的 `squashfs-factory.bin` 和 `squashfs-sysupgrade.bin`；

HomeWRK 下载以下两个文件，均选择文件名含 `linksys_homewrk` 的镜像：

- `initramfs-uImage.itb`：从 USB 启动临时系统，使用本发布组附带的 ImmortalWrt 官方最新稳定 Release 原版镜像。
- `squashfs-sysupgrade.bin`：在临时系统的 LuCI 后台安装正式固件。

首次安装按本教程使用上述两个文件，无需下载或刷入 `factory.ubi`，也无需另去官方网站下载临时镜像。

HomeWRK 临时镜像直接下载官方原版，不重新编译、不添加软件、不修改默认配置，管理地址为 `192.168.1.1`。

## 二、MX4200 / MX4300：原厂后台刷入

### 1. 刷入 factory 固件

1. 电脑用网线连接路由器 **LAN 口**，关闭电脑 Wi-Fi，有线网卡设置为自动获取 IP。
2. 浏览器打开原厂后台，通常为 `192.168.1.1`；打不开时查看电脑有线网卡的默认网关。
3. 登录原厂管理员账号，点击页面底部 **CA**，进入 **Connectivity / 连接**。
4. 选择对应机型的 `squashfs-factory.bin`，点击 **Start / 开始**，等待更新并重启。

找不到上传入口时，可打开 `https://路由器IP/fwupdate.html`。出现型号不匹配或校验失败就停止，不要强刷。

### 2. 在新系统后台再升级一次

1. 电脑重新获取 IP，打开新系统后台 `http://192.168.10.1`。
2. 进入 **系统 → 备份 / 升级 → 刷写新的固件**。
3. 上传对应机型的 `squashfs-sysupgrade.bin`，**取消勾选“保留配置”**。
4. 校验通过后开始升级，等待重启。若有“升级当前分区”选项，**不要勾选**。

原生升级流程默认写入另一分区并切换启动，这样两个分区都是新系统，另一槽原厂系统也会被覆盖。**不需要 SSH 或手动补刷分区命令。**

## 三、HomeWRK：Windows＋TTL 刷入

### 1. 准备工具

- Windows 电脑、网线、可清空的 U 盘。
- **3.3V USB-TTL** 模块及其 Windows 驱动。
- [PuTTY 中文版](https://github.com/larryli/putty)：连接串口，从项目 Releases 下载。
- [Rufus](https://rufus.ie/zh/)：制作启动 U 盘，下载官方便携版即可。
- HomeWRK 的 `initramfs-uImage.itb` 和 `squashfs-sysupgrade.bin`。

### 2. 制作启动 U 盘

1. 在资源管理器中开启“文件扩展名”，将 HomeWRK 临时镜像重命名为 `initramfs.img`，不解压、不转换格式。
2. 插入 U 盘，以管理员身份打开 Rufus，在“设备”中选择 **U 盘**，核对型号和容量。
3. 按 **Alt＋M**，确认已启用“忽略启动标记”检查，让 Rufus 接受路由器的原始镜像。
4. 点击“选择”，打开 `initramfs.img`，点击“开始”。若提示写入方式，选择 **DD 镜像模式**，不要选 ISO 模式。
5. 确认清空 U 盘，等待写入完成。

无需提前格式化 U 盘，不要手动更改文件系统或分区表。

**这会清空整个 U 盘，不能选电脑硬盘。不是把镜像复制进 U 盘；写完后 Windows 若提示格式化，点取消。**

### 3. 接 TTL，打开 PuTTY

路由器断电后接线。**白色六针串口插座从左到右前四针为 GND、TX、空、RX**。第 3 针留空，其余针脚也不接。

```text
从左到右：  第1针   第2针   第3针   第4针
路由器：    GND     TX      空      RX
TTL 接线：  GND     RX      不接    TX
```

**只接这三根线，不接 VCC，不能使用 5V TTL 或 RS-232。路由器使用原装电源供电。**

插入 USB-TTL，在 Windows **设备管理器 → 端口**查看 COM 号，PuTTY 设置：

```text
连接类型：串口（Serial）
串口：实际 COM 号，例如 COM3
速度：115200
数据位：8
停止位：1
校验：无（None）
流控：无（None）
```

打开串口，将 U 盘插入路由器，再给路由器通电。看到 `Hit any key to stop autoboot` 提示时按键，中断启动，停在 U-Boot 命令行。

### 4. 启动临时系统

在 PuTTY 的 **U-Boot 命令行**执行：

```text
usb start && usbboot 44000000 0 && bootm 44000000
```

临时系统运行在内存中，此时尚未将新系统写入闪存。启动完成后，TTL 操作到此结束，接下来在 LuCI 网页中完成安装。读取或启动失败时先停止，不继续刷写。

### 5. 在 LuCI 后台刷入正式固件

1. 电脑用网线连接 HomeWRK 的 **LAN 口**，关闭电脑 Wi-Fi，有线网卡自动获取 IP。
2. 浏览器打开 `http://192.168.1.1`，进入临时系统的 LuCI 后台，使用 `root` 登录，初始无密码。
3. 进入 **系统 → 备份 / 升级 → 刷写新的固件**。
4. 上传 **HomeWRK** 的 `squashfs-sysupgrade.bin`，**取消勾选“保留配置”**。
5. 校验通过后开始刷写，等待重启，不断电、不拔 U 盘；完成后移除 U 盘。

出现不兼容或校验错误就停止，不要强制刷入。这里不需要 WinSCP，也不需要命令行上传固件。

本发布组每次构建自动获取官方最新稳定 Release 的 HomeWRK 临时镜像，并核对官方公布的大小和 SHA-256，不固定版本。

## 四、刷完登录与以后升级

电脑重新获取 IP，打开 `http://192.168.10.1`，用户名 `root`，初始管理密码为空。无线等设置见 [README](README.md#默认设置)。HomeWRK 临时系统使用 `192.168.1.1`，正式安装后改为 `192.168.10.1`。

登录后设置管理员密码和 Wi-Fi 密码。以后升级直接在 **系统 → 备份 / 升级** 上传对应机型的 `sysupgrade.bin`，建议不保留配置，无需再次启动临时系统。

## 参考

- [OpenWrt：MX4200 v1 / v2](https://openwrt.org/toh/linksys/mx4200_v1_and_v2)
- [OpenWrt：MX4300](https://openwrt.org/toh/linksys/mx4300)
- [HomeWRK 上游安装说明](https://github.com/openwrt/openwrt/commit/07f8319d2d9166a41c2fd94ec1422bcd80ada991)

本文按官方资料与镜像内容核对，未进行实机刷写。
