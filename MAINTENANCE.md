# 构建维护

基于 immortalwrt/immortalwrt 官方 `master` snapshot；HomeProxy、sing-box 使用 yahuisme/packages 包源，sing-box 仅跟随官方正式版，Aurora 跟随其上游。包替换阶段输出实际提交。保留定制版本显示、MX4200v1/v2、Mesh/AP 和 USB 存储功能。

长期原则与 W1700K 一致：官方为主，只做既定参数定制，只补有证据的必要缺口，非必要不加补丁。不为恢复 fork 额外能力导入 NSS、驱动增强或理论性能优化；参数值保留不代表官方驱动、固件及硬件能力与旧 fork 等价。无线功率须区分 UCI 请求值与实际监管/驱动读回。

## 缓存

- 工具缓存：最终配置、源码内容、文件模式、绝对构建路径及 runner 环境共同生成精确 key，无前缀回退。配套保存 host 与 toolchain 的 build_dir、staging_dir，不缓存目标或 hostpkg 产物。
- 配置指纹仅忽略最终配置中规范的未选中包注释，保留其他字节；异常格式回退全量指纹，不改写 `.config`。配置策略独立版本化，首次使工具链及派生 hostpkg 冷填充，下载与 ccache 继续复用。
- `cache-inputs sha256/16` 按实际指纹输入输出分组摘要；`.config` 为上述过滤后的摘要，不是原文件校验值。hostpkg 自身的 feed 配方变化仍会使其失效。
- 下载缓存：dl 与 ccache 合并滚动更新；ccache 本地上限暂设 2G，不代表远程总量上限。
- 只规范源码输入时间，不修改完成标记。PAX 保留纳秒时间，pigz 快速压缩；归档压缩一次后复用，Actions 仍有外层包装。
- 三层（toolchain、hostpkg、dl + ccache）依次按实测归档大小与全仓库库存检查 10GB 共存预算。超限不上传、不删除；只有新缓存精确读回后才清理本层、本 ref 的旧条目。没有旧格式迁移或跨层删除。
- 镜像验证后依次尝试三层缓存，最后发布；缓存失败不阻止已验证镜像发布，发布失败仍使任务失败。取消或镜像验证失败不发布；全工作流串行，正式发布及缓存写入限定 main。

## 本地验证

GnuTLS 包准备后通过真实 `include/autotools.mk` 检查 hook，仅在重复时删除包配方的冗余 `autoreconf`，保留 gettext 与一次 autoreconf；已修复上游不改写，未知行为停止构建。不修改全局 include 或缓存算法，包输入变化仍会正常更新 hostpkg key。正常并行编译使用默认输出，仅串行失败重试保留 `V=s`。

安装 PyYAML，运行 `python3 -m unittest discover -v`、`actionlint .github/workflows/MX4200.yml` 和 `git diff --check`。

`GNUTLS_PRISTINE_SOURCE` 可指定包含真实 GnuTLS feed 配方及 `include/autotools.mk` 的源码根以验证 hook；这不等于 GnuTLS 编译。`SETTINGS_PRISTINE_SOURCE` 指向只含真实设置模板的窄树；`MX4200_PRISTINE_SOURCE` 提供原版 autocore，`MX4200_PREPARED_SOURCE` 提供真实 defconfig 结果，`HOMEPROXY_AUDIT` 用于两提交回放（见 Tests/fixtures/hostpkg/README.md）。温度回归需要 BusyBox。

## 官方基线必要差异

- 非必要组件遵循官方默认，不强选旧 fork 隐含的 ext4/f2fs 工具与驱动。官方 qualcommax 默认提供 wpad-openssl，无需重复选择，基础无线及 Mesh/AP 支持保留。移除可选 usbutils 的旧显式选择，不为其 libudev-zero 依赖额外启用 input-support；既有基础 USB 存储支持和其他已选应用、个人参数不变。
- 版本显示沿用 `ImmortalWrt r<官方提交计数>-<Git缩写>`：openwrt_release 的描述、os-release 的 PRETTY_NAME/OPENWRT_RELEASE 和 banner 不显示 SNAPSHOT；机器字段 VERSION/DISTRIB_RELEASE 仍为 SNAPSHOT。保留真实 getver 与源码提交日期，不补旧 fork 的计数差、不启用 VERSIONOPT。Release tag/title 的格式与香港构建时间来源不变；LuCI 经 procd `system.board` 读取 OPENWRT_RELEASE，再附加独立的 LuCI 版本。
- 默认 SSID/key 与 WPA2 `psk2+ccmp` 一起设置，避免官方默认开放加密覆盖既定密码约定。首启 overlay 保持原样，包括香港时区、US、48/11/149、25/23/25、禁用1/0/0及5G模式沿用。
- `Temperature.py` 只修复 autocore 通用 Wi-Fi 读数循环：单个已存在但读返回 EIO 的传感器不再中断后续 phy 的读取，忽略非数字，不伪造 0°C。保留官方 RPC/界面及无读数表现；不写死 radio0/phy0。BusyBox 隔离测试覆盖三路各自单独可读、三路同时可读、仅第三路可读而前两路 EIO。此为真实脚本模拟，不是设备启停/信道测试。
- 官方目标、DTS、监管和 ath11k 不新增补丁；官方已有功率设置链，不复制 DD-WRT 固件。NSS 与旧固件硬件表现不宣称等价，构建和实机仍需单独授权。

设置 `CACHE_OPENWRT_ROOT` 为专用官方测试源码树，可启用真实 flock 冷编译、归档恢复与热构建测试；该测试会修改测试树，请勿指向正在使用的编译目录。禁止本地编译的审计不得启用此项。普通测试不访问远程缓存或发布 API。

原生 host 测试不等于 x86 完整工具链或固件冷热验证。生产归档容量及实际提速需在另行授权的 CI 中测量；不得通过放宽精确匹配制造命中。
