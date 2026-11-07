"""Official snapshot-source defaults and intentional customization requirements."""
import os
import re
from pathlib import Path
import unittest
import yaml
from scripts.check_defaults import check
from scripts.external_packages import REPOSITORIES

ROOT = Path(__file__).resolve().parents[1]


class OfficialMigrationTests(unittest.TestCase):
    def assert_native_dataplane(self, config, target):
        flattened = target.replace('\\\n', ' ')
        defaults = set()
        for row in re.findall(r'^DEFAULT_PACKAGES\s*\+=\s*(.*)$', flattened, re.M):
            defaults.update(row.split())
        native = {package for package in defaults if package.startswith('kmod-qca-nss-')}
        # Reviewed official target owns this driver; do not whitelist arbitrary new
        # target symbols or conflate it with external acceleration integrations.
        self.assertEqual(native, {'kmod-qca-nss-dp'})
        selected = {line.split('=', 1)[0].removeprefix('CONFIG_PACKAGE_')
                    for line in config if line.startswith('CONFIG_PACKAGE_kmod-qca-nss-')
                    and line.rsplit('=', 1)[-1] in ('y', 'm')}
        self.assertEqual(selected, native)
        self.assertIn('CONFIG_PACKAGE_kmod-qca-nss-dp=y', config)

    def test_official_dataplane_is_preserved_and_unexpected_symbols_rejected(self):
        target = 'DEFAULT_PACKAGES += \\\n\tkmod-qca-nss-dp kmod-ath11k-ahb wpad-openssl\n'
        config = ['CONFIG_PACKAGE_kmod-qca-nss-dp=y']
        self.assert_native_dataplane(config, target)
        for extra in ('kmod-qca-nss-ecm', 'kmod-qca-nss-drv', 'kmod-qca-nss-unknown'):
            for value in ('y', 'm'):
                with self.subTest(extra=extra, value=value), self.assertRaises(AssertionError):
                    self.assert_native_dataplane(config + [f'CONFIG_PACKAGE_{extra}={value}'], target)
        with self.assertRaises(AssertionError):
            self.assert_native_dataplane([], target)
        with self.assertRaises(AssertionError):
            self.assert_native_dataplane(config, target.replace('kmod-qca-nss-dp', ''))

    def test_signed_apk_package_selection_is_theme_only(self):
        self.assertEqual(set(REPOSITORIES), {'eamonxg'})
        self.assertEqual(REPOSITORIES['eamonxg']['packages'], [
            'luci-theme-aurora', 'luci-app-aurora-config', 'luci-i18n-aurora-config-zh-cn',
        ])

    def test_official_source_and_release_description(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())
        settings = (ROOT / 'user/default/settings.ini').read_text()
        self.assertIn('REPO_URL="https://github.com/immortalwrt/immortalwrt.git"', settings)
        self.assertIn('REPO_REF="master"', settings)
        self.assertNotIn('REPO_BRANCH=', settings)
        self.assertIn('最新 snapshot 源码', (ROOT / 'README.md').read_text())
        text = (ROOT / '.github/workflows/MX4200.yml').read_text()
        self.assertNotIn('git ls-remote --tags', text)
        self.assertIn('git fetch --depth=1 origin "$SOURCE_REF"', text)
        self.assertIn('SOURCE_REF="refs/heads/$REPO_REF"', text)
        self.assertIn('SOURCE_REF=', text)
        self.assertIn('SOURCE_SHA', text[text.index('RELEASE_NOTES='):])
        self.assertIn('SOURCE_URL', text[text.index('RELEASE_NOTES='):])
        self.assertNotIn('SOURCE_VERSION=', text)
        self.assertIn('VERSION="${DEVICE}-ImmortalWrt-r${WRT_REV}-${WRT_DATE/-/_}"', text)
        self.assertIn('DEVICE=MX4200', text)
        self.assertIn('DEVICE=MX4300-HomeWRK', text)
        self.assertIn('printf \'%s\\n\' "$VERSION" > "firmware/$GROUP/title.txt"', text)
        self.assertEqual(workflow['jobs']['build']['runs-on'], 'ubuntu-24.04-arm')
        self.assertNotIn('集成 NSS', (ROOT / '.github/workflows/MX4200.yml').read_text())

    def test_optional_donor_components_follow_official_defaults(self):
        config = (ROOT / 'user/default/config.diff').read_text().splitlines()
        # External signed APKs are not source selectors. Their runtime and
        # kernel dependencies must already be available in the local rootfs.
        positive = {line.split('=', 1)[0].removeprefix('CONFIG_PACKAGE_')
                    for line in config if line.startswith('CONFIG_PACKAGE_')
                    and line.endswith('=y')}
        self.assertEqual(positive, {
            'luci', 'autocore', 'luci-app-advanced-reboot',
            'luci-app-ttyd', 'luci-app-wol', 'curl',
            'luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box',
        })
        self.assertIn('CONFIG_PACKAGE_luci-app-attendedsysupgrade=n', config)
        for package in ('luci-theme-aurora', 'luci-app-aurora-config',
                        'luci-i18n-aurora-config-zh-cn'):
            self.assertFalse(any(line.startswith('CONFIG_PACKAGE_' + package + '=')
                                 for line in config), package)
        for symbol in ('KERNEL_CGROUPS',
                       'KERNEL_CGROUP_BPF', 'KERNEL_NAMESPACES', 'KERNEL_NET_NS'):
            self.assertFalse(any(line.startswith('CONFIG_' + symbol + '=')
                                 for line in config), symbol)
        for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn'):
            for value in ('y', 'm'):
                self.assertNotIn('CONFIG_PACKAGE_' + package + '=' + value, config)

    @unittest.skipUnless(os.environ.get('MX4200_PREPARED_SOURCE'),
                         'set MX4200_PREPARED_SOURCE for native defconfig closure')
    def test_native_prepared_package_closure(self):
        source = Path(os.environ['MX4200_PREPARED_SOURCE'])
        config = (source / '.config').read_text().splitlines()
        check('\n'.join(config), (source / 'tmp/.packageinfo').read_text())
        for package in ('luci-app-attendedsysupgrade', 'luci-i18n-attendedsysupgrade-zh-cn',
                        'attendedsysupgrade-common', 'auc', 'owut'):
            for value in ('y', 'm'):
                self.assertNotIn('CONFIG_PACKAGE_' + package + '=' + value, config)
        for package in ('luci-app-firewall', 'luci-app-package-manager', 'autocore',
                        'luci-i18n-firewall-zh-cn', 'luci-i18n-package-manager-zh-cn',
                        'kmod-usb3', 'kmod-usb-storage', 'curl', 'etherwake', 'ttyd',
                        'luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box',
                        'firewall4', 'kmod-nft-queue', 'kmod-tun', 'kmod-inet-diag',
                        'kmod-netlink-diag', 'flock', 'unzip', 'ucode-mod-digest', 'ucode-mod-math'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        for package in ('kmod-bonding', 'proto-bonding', 'kmod-fs-btrfs', 'kmod-fuse',
                        'kmod-wireguard', 'kmod-inet-mptcp-diag', 'kmod-mtd-rw',
                        'kmod-tcp-bbr',
                        'exfat-fsck', 'exfat-mkfs', 'fdisk', 'gdisk', 'smartmontools',
                        'smartmontools-drivedb', 'iperf3', 'htop',
                        'openssh-keygen', 'openssh-sftp-server', 'openssl-util',
                        'blkid', 'dmesg', 'lsblk', 'nand-utils', 'xz-utils'):
            for value in ('y', 'm'):
                self.assertNotIn('CONFIG_PACKAGE_' + package + '=' + value, config)
        requested = (ROOT / 'user/default/config.diff').read_text().splitlines()
        for line in requested:
            if line.startswith('CONFIG_PACKAGE_') and line.endswith('=y'):
                self.assertTrue(line in config, line)
        for device in ('mx4200v1', 'mx4200v2', 'mx4300', 'homewrk'):
            self.assertIn('CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_' + device + '=y', config)
        for package in ('luci-i18n-advanced-reboot-zh-cn', 'luci-i18n-wol-zh-cn',
                        'luci-i18n-ttyd-zh-cn', 'ath11k-firmware-ipq8074',
                        'wpad-openssl', 'kmod-ath11k-ahb'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        self.assert_native_dataplane(config, (source / 'target/linux/qualcommax/Makefile').read_text())
