# 构建维护

本仓库基于 ImmortalWrt 官方 `master`，构建 MX4200v1/v2 固件。

## 主要文件

- `.github/workflows/MX4200.yml`：手动或定时构建。
- `docker/`：CI 构建环境。
- `user/default/`：源码地址、设备配置和默认参数。
- `scripts/settings.sh`：主题、网络、无线及版本显示设置。
- `scripts/packages.sh`：获取 Aurora、HomeProxy 和 sing-box。
- `scripts/release_images.py`、`scripts/verify_release.py`：检查并发布固件文件。
- `scripts/build_record.py`：保存构建信息。
