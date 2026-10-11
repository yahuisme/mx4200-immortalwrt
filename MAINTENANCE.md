# 构建维护

基于 ImmortalWrt 官方 `master` snapshot，构建 MX4200v1/v2。
保留官方设备默认包及完整依赖，只添加指定应用、个人参数和有证据的必要修正；不继承旧项目额外软件包或 NSS。

## 文件职责

- `Config/MX4200.txt`：设备、构建开关、中文 LuCI 与指定应用；依赖交给官方配方，保留 hci-uart 必需的 input-support。
- `Scripts/Packages.sh`：获取 Aurora、HomeProxy、sing-box；在临时克隆删除前输出并记录实际包源提交。
- `Scripts/BuildRecord.py`：保存最终配置、包清单、源码提交、镜像 SHA-256 与构建环境，仅作为保留 30 天的 Actions artifact；记录失败不阻断有效镜像发布。记录必须完整匹配实际 source/recipe、所有 Git feeds 和临时克隆时保留的三个 custom SHA。发布后核验四个附件的名称、大小、uploaded 状态及 SHA-256；缺少 digest 时流式下载核对，下载失败或 hash 不符不清理旧版，通过后才按原策略保留最新两版。
- `Scripts/Settings.sh`、`files/`：主题、版本显示、管理地址与无线默认值；排除 attendedsysupgrade。
- `Scripts/Temperature.py`：修正单路传感器读取失败中断其他无线温度的问题。
- `Scripts/CheckDefaults.py`：defconfig 后核验全部设备默认包及虚拟提供者，并复用 `Config/MX4200.txt` 的显式 PACKAGE=y/n：指定应用必须 y，排除包不得 y/m。
- `.github/workflows/MX4200.yml`：准备、构建、校验镜像与发布；GnuTLS/GoBootstrap 脚本处理构建前置要求。

## ath11k 内存模式

`Settings.sh` 仅为 MX4200v2 的官方 `&wifi` 模板添加 `qcom,ath11k-fw-memory-mode = <1>;`，重复执行不再改写；模板、已有模式值或节点数量不符即失败，避免覆盖上游变化。官方 `903-ath11k-support-setting-FW-memory-mode-via-DT.patch` 原生支持该模式：每 radio 的 VDEV/peer 预算由 17/512 降为 8/128，多 SSID、Mesh 与客户端容量相应受限；128 不代表任何组合下都可接入 128 个客户端。

v1、v2 均使用 mode 1 与 64 MiB Q6，起始地址保持 0x4b000000；在设备 DTS 末尾设置预留区，避免公共 include 覆盖。其他预留区及 ring/SKB 不变。静态检查不替代实机冷启动校准与持续无线负载验证。

## 缓存

三层缓存为 toolchain、hostpkg、dl + ccache；源码与最终配置参与精确匹配，下载及 ccache 滚动复用。
按仓库 10GB 总预算保存，仅在新缓存确认可读后清理本层旧条目；超限不上传、不删除。

## 验证

```sh
python3 -m unittest discover -v
actionlint .github/workflows/MX4200.yml
git diff --check
```

真实配置检查设置 `MX4200_PREPARED_SOURCE`；原版源码设置 `MX4200_PRISTINE_SOURCE`（温度）、`GNUTLS_PRISTINE_SOURCE`（配方），设置模板用 `SETTINGS_PRISTINE_SOURCE`（包含原版设置文件、MX4200v1/v2 DTS、qualcommax 预留内存文件与 ath11k patches；测试完整 Settings 及平台文件字节边界）。温度测试需要 BusyBox。原生 LED 隔离测试设置 `MX4200_TEST_ROOTFS` 为已解包、可在宿主执行的 OpenWrt/ImmortalWrt rootfs，使用 root 执行 `python3 -m unittest Tests.test_native_leds -v`；测试将真实 UCI、ash、LED 服务与 diag 复制到临时 chroot，只模拟 sysfs/设备树，不挂载或操作宿主硬件。未设置时明确跳过，不能当作已验证。
`HOMEPROXY_AUDIT` 的两提交源码布局见 [测试夹具说明](Tests/fixtures/hostpkg/README.md)。完整非编译验证须提供上述环境变量并检查跳过项。
禁止本地编译时不要设置 `CACHE_OPENWRT_ROOT`，该项会实际编译 flock；推送、触发构建及发布须另行授权。
