# 构建维护

本仓库基于 ImmortalWrt 官方 `master`，构建 MX4200v1/v2 固件。

## 构建规则

- 使用 ARM64 runner 和 Debian ARM64 Docker 环境，源码与固件均在 CI 中处理。
- 保留官方设备配置、默认软件包及完整依赖，只加入仓库明确指定的功能。
- 不使用 usteer，不恢复旧的 VIKING/NSS 方案，也不自动覆盖 HomeProxy。
- v1/v2 的无线内存模式和 Q6 预留使用官方默认值，不在脚本中修改：v1 为 55 MiB，v2 为 95 MiB。
- 发布只包含 v1/v2 的 factory 和 sysupgrade 固件，不加入诊断文件或其他元数据。

## 主要文件

- `.github/workflows/MX4200.yml`：手动或定时构建。
- `docker/`：CI 构建环境。
- `user/default/`：源码地址、设备配置和默认参数。
- `scripts/settings.sh`：主题、网络、无线及版本显示设置。
- `scripts/packages.sh`：获取 Aurora、HomeProxy 和 sing-box。
- `scripts/release_images.py`、`scripts/verify_release.py`：检查并发布四个固件文件。
- `scripts/build_record.py`：保存构建版本、源码和固件校验信息。

## 缓存与验证

工具链、编译器和下载缓存分别保存，使用 MX4200 ARM64 专用名称空间。缓存失败时保留旧缓存，不影响后续诊断。

本地只做脚本和测试验证，不编译真实固件：

```sh
/opt/test-tools/bin/run-bounded-test python3 -m unittest discover -s tests -v
actionlint .github/workflows/MX4200.yml
git diff --check
```

缺少官方源码、真实 rootfs 或硬件时，相关测试必须明确标记为未验证，不能当作通过。

禁止本地真实固件编译。提交、推送、触发 CI 和发布固件均需单独授权。
