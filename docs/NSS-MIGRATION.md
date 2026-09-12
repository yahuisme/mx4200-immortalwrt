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

### NSS 用户态与可选能力

`iproute2` 同时移植 donor 正式版的 `400-add-nss-qdisc.patch` 和 `500-add-nssmirred.patch`，为 `tc` 提供 NSS qdisc 与 ingress redirect 解析器。策略监控整个 iproute2 包的 donor 差异（包括 Makefile），避免补丁改名或构建开关变化漏审；未审核改动仍中止准备。

MX4200 默认安装 `tc-full` 以及当前内置配方中适用于 IPQ807x、未标记 `BROKEN` 的全部 clients：bridge / VLAN / PPPoE、qdisc / IGS、6rd / IPIP6、L2TPv2 / PPTP、MAP-T、GRE / EoGRE、LAG、VXLAN、netlink、match / mirror 和 Wi-Fi Mesh manager。保留 NSS 11.4、ECM 与 ath11k Mesh 组合。**编入可用、开机加载、规则生效是三件事**：有实际收益的加速管理器沿用上游自动加载；需要业务配置的能力保留可用，不为“全开”启动无用服务，不创建整形、隧道、镜像或测速规则。

| 能力 | 默认加载 / 启动 | 配置边界 |
| --- | --- | --- |
| bridge、VLAN、PPPoE、LAG、GRE、L2TPv2、PPTP、MAP-T、VXLAN、Wi-Fi Mesh manager | 配方 `AutoLoad,51` | 管理已有接口 / 连接，不代建业务配置 |
| 6rd、IPIP6 manager | 配方 `AutoLoad,60` | 同上，实际隧道须配置 |
| qdisc | 编入，不新增开机加载 | 模块初始化注册 NSS 调度器；整形仍需指定接口、算法和带宽。使用前显式 `modprobe qca-nss-qdisc`，不把安装包当成已开启限速 |
| IGS / nssmirred | 编入，不新增开机加载 | `act_nssmirred` 注册 tc action / notifier；需 IFB 与 redirect 规则。配方没有安装旧 `qca-nss-mirred.init`，该脚本也无 `START` |
| netlink | 编入，init 脚本无 `START`，不随镜像开机启动 | 模块注册控制 / 统计 family；手动启动旧脚本还会把两个 N2H queue limit 写成 2048，无明确需求不启动 |
| match / mirror、EoGRE manager | 编入，无 `AUTOLOAD` | match / mirror 注册控制接口，镜像接口 / 规则需要显式请求；不自动复制流量 |

IGS 依赖的官方 `kmod-ifb` 会自动加载，但 `MODPARAMS.ifb:=numifbs=0`，不会凭空创建 IFB 接口。以上是配方和 NSS 11.4 clients `c4049d1` 加本地补丁后的源码行为审查，不是实机内存、吞吐或 ECM 影响测量；不承诺模块零开销。netlink 的“不自动启动”专指固件启动：OpenWrt 在线安装包的 postinst 可能直接调用 init `start`，不可据此推断在线安装无副作用。

“全套”限定为当前开源配方与目标支持范围，而非闭源 QSDK 全功能：DTLS / TLS、IPsec 及其插件、CAPWAP、PVXLAN、CLMAP 标记 `BROKEN`；OpenVPN offload 配方还未注册；profiler 仅适用于 IPQ806x，MSCS 仅适用于 qualcommbe，均不强行启用。普通软件 VPN 可用性与 NSS VPN 加速是不同事项。包可被配置选中不证明其内核编译或固件运行正常，仍需完整构建和实机验证。

本次真实验证使用官方 / donor `v25.12.2`，iproute2 `6.18.0` 归档 SHA-256 为 `6ba520e1975e4c50dc931eeae91ea37c198b8a173744885f8895b84325f9d456`：官方 19 个补丁加两个 NSS 补丁按顺序以 `--fuzz=0` 全部应用；宿主原生编译完成 `q_nss.o`、`m_nssmirred.o` 并链接可执行 `tc`，NSS qdisc / action 帮助解析成功。该编译未启用宿主缺失的 libbpf / libmnl 等可选库，不等于 OpenWrt tc-full 交叉编译。真实源树 `make defconfig` 保留上述全部 clients、tc-full、SHAPER / IGS 开关；该隔离验证树未安装 feeds，因此不作为完整产品配置验证。

## 验证

仓库回归测试：

```sh
python3 -m unittest discover -s Tests -v
```

真实源码准备并配置后，在生成的构建树执行 `make defconfig`，再运行仓库中的 `Scripts/Verify.py config <构建树>`，检查必选项、禁用项和设备范围。

NSS 集成测试可使用以下真实产物，未提供对应变量时明确跳过：

```sh
NSS_OFFICIAL=/path/to/official NSS_DONOR=/path/to/donor \
NSS_CONFIG=/path/to/build/.config NSS_TC=/path/to/compiled/tc \
python3 -m unittest Tests.test_nss_tc -v
```

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
