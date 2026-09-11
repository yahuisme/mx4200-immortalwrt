# MX4200 本地迁移交接

## 工作区

- 待审工作树：`/root/mx4200-official-nss`
- 分支：`migrate-official-nss`
- 基线：`5c62b00065e3c81c2335a3a136f61d688b8d6c84`
- 全部改动未提交；未 push、dispatch 或发布。原有分歧工作树没有重置。
- 用户要求在新会话独立审查，未经单独授权不提交、推送或构建发布。

## 实现范围

动态解析官方 ImmortalWrt 最新正式版，以 LiBwrt 对应正式版提供经审查的 NSS 内核/无线差异，借鉴 VIKINGYFY 的 `package/qca-nss/` 内置包配方布局。核心包来自记录的 qosmio 版本；保留 Git 源及 PKG_MIRROR_HASH，firmware 使用 qosmio Release 归档及原 SHA256。不使用自建归档、skip 或修改上游摘要。保留 MX4200v1/v2、现有应用、设置及 dl/ccache。

主要审查对象：`Scripts/Prepare.py`、`Scripts/Verify.py`、`Scripts/Packages.sh`、`Config/nss-policy.json`、`Config/NSS.txt`、`package/qca-nss/`、workflow、overlay、Tests、README。

## 已查明并修正的问题

先前把 Git 源码包误称为无需归档校验、把 firmware 11.4 条件分支误判为重复定义，均不正确。drv/clients 合法条件分支已恢复，Mesh 11.4 组合为 drv 53e5863、clients c4049d1、ECM 30fbfa4。

归档 SHA256 不匹配来自本机 root 执行 GNU tar 时保留 Git archive 的 0664/0775 权限，与普通用户 umask 022 下的 0644/0755 不同。无需新镜像、改变源码或 hash。root 本地复现使用：

```sh
umask 022
make <target>/prepare -j1 V=s 'TAR=tar --no-same-permissions'
```

不要覆盖 TAR_OPTIONS。正常 CI 为非 root 构建，不应为本地权限问题无谓改造下载系统。完整证据见 `docs/nss-prepare-verification.md`。

## 真实验证结果

验证源码树：`/root/mx4200-nss-investigation/verified-core`。

- Prepare.py、真实 feeds、定制脚本、overlay、make defconfig 已执行；95 项必需配置及仅 MX4200v1/v2 通过。
- 删除三个核心包下载缓存并 clean 后，重新下载、原 SHA256 验证及补丁 prepare：drv、ECM、clients 均 exit 0。
- Linux 6.12.103、mac80211 backports 6.18.39、NSS firmware prepare 均 exit 0。
- 父会话重新执行 `python3 -m unittest discover -s Tests -q`：14 项通过；`git diff --check` 通过。
- 测试中的四镜像是合同测试 fixture，不是真实固件产物。

日志与结果位于 `/root/mx4200-nss-investigation/`：`verified-cold-results.json`、`verified-cold-*.log`、`verified-mesh-{kernel,mac80211,nss-firmware}.log`、`mode-probe.json`。

## 新会话必须复核

- 尚未完整编译固件或实机验证；prepare 通过不等于完整可发布。
- 尚有未选中可选依赖警告及补丁 fuzz/offset，逐项判断是否影响选中功能。
- 核查动态正式版策略与内置 qosmio 包的更新机制，不能把运行时自动发现官方新版本误称为所有 NSS 组件会自动升级。
- 审查差异策略是否不必要地阻断无关更新、184 个内置包文件是否均必要、缓存键是否能持续保存新缓存。
- 核查 firmware 11.4、Mesh/AP、三频无线、代理分流及默认卸载配置。实机功能未验证。
- 全面审阅 workflow 与 README 的准确性，禁止未经授权发布。
