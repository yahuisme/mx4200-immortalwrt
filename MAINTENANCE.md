# 构建维护

基于 VIKINGYFY/immortalwrt `main`；HomeProxy、sing-box 使用 yahuisme/packages 包源，sing-box 仅跟随官方正式版，Aurora 跟随其上游。包替换阶段输出实际提交。保留定制版本显示、MX4200v1/v2、Mesh/AP 和 USB 存储功能。

## 缓存

- 工具缓存：最终配置、源码内容、文件模式、绝对构建路径及 runner 环境共同生成精确 key，无前缀回退。配套保存 host 与 toolchain 的 build_dir、staging_dir，不缓存目标或 hostpkg 产物。
- 下载缓存：dl 与 ccache 合并滚动更新；ccache 本地上限暂设 2G，不代表远程总量上限。
- 只规范源码输入时间，不修改完成标记。PAX 保留纳秒时间，pigz 快速压缩；归档压缩一次后复用，Actions 仍有外层包装。
- 三层（toolchain、hostpkg、dl + ccache）依次按实测归档大小与全仓库库存检查 10GB 共存预算。超限不上传、不删除；只有新缓存精确读回后才清理本层、本 ref 的旧条目。没有旧格式迁移或跨层删除。
- 缓存上传在镜像验证与发布后执行，失败不影响已发布固件。全工作流串行，正式发布及缓存写入限定 main。

## 本地验证

GnuTLS 包准备后通过真实 `include/autotools.mk` 检查 hook，仅在重复时删除包配方的冗余 `autoreconf`，保留 gettext 与一次 autoreconf；已修复上游不改写，未知行为停止构建。不修改全局 include 或缓存算法，包输入变化仍会正常更新 hostpkg key。正常并行编译使用默认输出，仅串行失败重试保留 `V=s`。

安装 PyYAML，运行 `python3 -m unittest discover -v`、`actionlint .github/workflows/MX4200.yml` 和 `git diff --check`。

`GNUTLS_PRISTINE_SOURCE` 可指定包含真实 GnuTLS feed 配方及 `include/autotools.mk` 的源码根以验证 hook；这不等于 GnuTLS 编译。`SETTINGS_PRISTINE_SOURCE` 可指定真实设置模板树。

设置 `CACHE_OPENWRT_ROOT` 为专用 VIKING 测试源码树，可启用真实 flock 冷编译、归档恢复与热构建测试；该测试会修改测试树，请勿指向正在使用的编译目录。普通测试不访问远程缓存或发布 API。

原生 host 测试不等于 x86 完整工具链或固件冷热验证。生产归档容量及实际提速需在另行授权的 CI 中测量；不得通过放宽精确匹配制造命中。
