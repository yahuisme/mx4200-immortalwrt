# 构建维护

基于 ImmortalWrt 官方 `master` snapshot，构建 MX4200v1/v2。
保留官方设备默认包及完整依赖，只添加指定应用、个人参数和必要修正。

## 文件职责

- `.github/workflows/MX4200.yml`：手动及每日构建；`ubuntu-24.04-arm` runner 上构建官方 Debian ARM64 Docker 环境。源码位于 `/bld/openwrt`，输出 `/bld/openwrt_bin`，`$DK_PROFILE` 指向 `/bld/user/default`。
- `docker/`、`scripts/builder_fingerprint.py`：环境镜像与兼容指纹；不预置源码或工具链。外部 Go 固定在镜像内 `/usr/lib/go`，`scripts/check_go.py` 以实际官方 feed bootstrap 配方校验版本下限，不使用 runner setup-go。
- `user/default/settings.ini`、`config.diff`、`custom.sh`、`files/`：官方源码地址、v1/v2 设备配置、定制入口与固件文件。硬件依赖交给官方配方，保留 hci-uart 所需 input-support。
- `scripts/packages.sh`：获取 Aurora、HomeProxy、sing-box；删除临时克隆前记录三个实际 custom SHA 至 `.custom-revisions.tsv`。
- `scripts/settings.sh`、`temperature.py`、`gnutls.py`：保留主题、显示版本、网络/Wi-Fi、DTS 内存、温度读取和 GnuTLS 既有行为。
- `scripts/check_defaults.py`：defconfig 后检查全部设备默认包、虚拟提供者及显式 PACKAGE=y/n，stage 时再次检查。
- `scripts/release_images.py`、`verify_release.py`：仅接收四个准确的 MX4200v1/v2 factory/sysupgrade 非空镜像；发布后校验名称、大小、状态、SHA-256，缺失 digest 时下载核对。
- `scripts/build_record.py`：保存最终配置、source/feed/custom 实际 SHA、包清单、profiles、四图校验值与环境；30 天 Actions artifact，不把诊断文件加入 Release，失败保留部分证据且不阻断有效镜像发布。

## 内存与发布边界

保留 v1/v2 mode 1 与 64 MiB Q6（起始 `0x4b000000`），DTS 末尾覆盖避免公共 include 改写；v2 模板变化即失败。其他预留区及 ring/SKB 不变。静态验证不等于实机冷启动校准或持续负载验证。

Release 沿用 `MX4200_ImmortalWrt_日期_r版本` tag 与 `MX4200-ImmortalWrt-r版本-日期_时间` 标题，保留当前及最近前版。发布与 prune 前各一次仅检查本仓库 `main` 是否仍等于 `$GITHUB_SHA`，不检查上游是否前进；Release 显式绑定该 SHA。API 失败或回复无效时不做后续变更。

## 缓存

完全分离 toolchain、ccache、download。精确工具链指纹含最终配置、qualcommax/generic 内核与构建输入、ARM 架构和受控 builder 指纹；排除 `generic/base-files`、`qualcommax/base-files`、`qualcommax/ipq807x/base-files` 运行时 overlay，不排除内核 patches/files。

新命名空间为 `tc-v1-mx4200-arm64-`、`cc-v1-mx4200-arm64.`、`dl-v1-mx4200-arm64.`，不恢复旧 x86、hostpkg 或合并 rolling 归档。各压缩包上限 2/3/3 GB，总预算 10 GB（包括旧缓存），不足时不上传或预删；新保存 readback 成功后才清理本层同分支旧条目。download 使用编译前后清单判断变化，包含编译期间生成的 Go module 下载。

## 本地验证

```sh
/opt/test-tools/bin/run-bounded-test python3 -m unittest discover -s tests -v
actionlint .github/workflows/MX4200.yml
git diff --check
```

完整非编译验证还需提供：`MX4200_PREPARED_SOURCE`（最终配置/packageinfo）、`IMMORTALWRT_SOURCE`（真实 cache 指纹域）、`MX4200_PRISTINE_SOURCE`（温度）、`GNUTLS_PRISTINE_SOURCE`、`SETTINGS_PRISTINE_SOURCE`（原版设置/DTS）、`MX4200_TEST_ROOTFS`（可执行原生 UCI/ash 的解包 rootfs）。缺失须报告跳过，不当成通过。测试只用临时 fixture、mock 编译/GitHub 边界；原生 LED 在独立 chroot 内执行。

禁止本地真实固件或 host 工具编译，勿运行可能自动编译的 make defconfig。commit、push、CI dispatch 和 Release 均需另行授权。
