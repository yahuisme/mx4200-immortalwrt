# NSS 维护说明

## 源码组成

- **系统基线**：ImmortalWrt 最新正式版，保留官方 feeds、设备定义与默认网络策略。
- **NSS 适配**：LiBwrt 对应正式版的内核、mac80211 / ath11k 和 hostapd 配套改动。
- **NSS 软件包**：`package/qca-nss/` 内置 qosmio 配方、补丁及启动脚本，沿用上游源码版本与归档摘要。
- **设备配置**：`Config/`、`Scripts/Settings.sh` 与 `files/` 管理 MX4200v1 / v2 的应用和默认设置。
- **HomeProxy 资源**：保留软件包自带规则及版本，dashboard 通过 HomeProxy 资源更新下载，不在固件构建时重复预置。

系统正式版在每次构建时解析；内置 NSS 配方不会自动升级，需单独审查更新。源码版本、移植指纹和定制包提交记录在 Actions 的 `source-lock` 附件中，不混入固件 Release。

## 适配边界

`Scripts/Prepare.py` 以 `Config/nss-policy.json` 为移植清单。未选中的文件保留官方版本，不引入 LiBwrt 品牌、默认应用或独立 IRQ / 网络调优脚本。

选中改动的内容、文件类型或权限变化，以及已知 NSS 扩展路径出现新文件时，准备流程会中止。官方与 donor 的正式版标签、内核版本也必须匹配。适配失败应审查实际差异，不应直接刷新指纹绕过检查。

指纹允许两边共有的上游上下文变化，但不能证明语义兼容。更新后仍需验证补丁应用、配置、完整编译和设备运行。

### Mesh 与固件版本

`Config/MX4200.txt` 选择 NSS 11.4，并启用 ath11k NSS Mesh。drv / clients 中的固件版本条件分支负责选择配套源码和补丁，不是重复定义；升级时应保持这一组合完整。

### MU-EDCA 配套

动态 MU-EDCA 需要 ath11k / mac80211 发送事件、hostapd 接收并更新 Beacon。除 donor 的 hostapd `900` 补丁外，还需 `patches/hostapd/901-hostapd-muedca-backports-abi.patch` 对齐两端 nl80211 编号。

更新 backports 或 hostapd 后，必须用实际头文件运行 ABI 测试；同名符号或补丁应用成功不代表编号一致。

## 验证

仓库回归测试：

```sh
python3 -m unittest discover -s Tests -v
```

真实源码准备并配置后，在生成的构建树执行 `make defconfig`，再运行仓库中的 `Scripts/Verify.py config <构建树>`，检查必选项、禁用项和设备范围。

MU-EDCA 集成测试需提供已应用补丁的源码目录：

```sh
MUEDCA_HOSTAPD=/path/to/prepared/hostapd \
MUEDCA_MAC80211=/path/to/prepared/backports \
python3 -m unittest Tests.test_muedca -v
```

未提供路径时，该集成测试会明确跳过。测试中的镜像文件仅为夹具；实际发布由 `Scripts/Verify.py images <构建树>` 收集 v1 / v2 各一份非空 factory 与 sysupgrade 镜像。

### 本地 root 下载验证

GNU tar 在 root 下默认保留 Git archive 权限，可能导致重新打包后的摘要与普通构建用户不同。在生成的构建树中验证时使用：

```sh
umask 022
make package/qca-nss/qca-nss-drv/prepare -j1 V=s 'TAR=tar --no-same-permissions'
```

其他 prepare 目标同理。保留原有 `PKG_MIRROR_HASH` / `PKG_HASH`，不要覆盖 `TAR_OPTIONS` 或跳过摘要校验。正常非 root CI 无需此参数。

完整构建结果以对应提交的 Actions 日志和 Release 为准。源码准备、单元测试与编译成功均不能替代实机 Mesh、无线和 NSS 加速验证。
