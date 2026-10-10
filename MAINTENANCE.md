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

## 缓存

三层缓存为 toolchain、hostpkg、dl + ccache；源码与最终配置参与精确匹配，下载及 ccache 滚动复用。
按仓库 10GB 总预算保存，仅在新缓存确认可读后清理本层旧条目；超限不上传、不删除。

## 验证

```sh
python3 -m unittest discover -v
actionlint .github/workflows/MX4200.yml
git diff --check
```

真实配置检查设置 `MX4200_PREPARED_SOURCE`；原版源码设置 `MX4200_PRISTINE_SOURCE`（温度）、`GNUTLS_PRISTINE_SOURCE`（配方），设置模板用 `SETTINGS_PRISTINE_SOURCE`。温度测试需要 BusyBox。
`HOMEPROXY_AUDIT` 的两提交源码布局见 [测试夹具说明](Tests/fixtures/hostpkg/README.md)。完整非编译验证须提供上述环境变量并检查跳过项。
禁止本地编译时不要设置 `CACHE_OPENWRT_ROOT`，该项会实际编译 flock；推送、触发构建及发布须另行授权。
