"""Official snapshot defaults and intentional customization requirements."""
import os
from pathlib import Path
import unittest
import yaml
from scripts.check_defaults import check

ROOT = Path(__file__).resolve().parents[1]


class OfficialMigrationTests(unittest.TestCase):
    def test_official_source_and_release_description(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())
        settings = (ROOT / 'user/default/settings.ini').read_text()
        self.assertIn('REPO_URL="https://github.com/immortalwrt/immortalwrt.git"', settings)
        self.assertIn('REPO_BRANCH="master"', settings)
        self.assertEqual(workflow['jobs']['build']['runs-on'], 'ubuntu-24.04-arm')
        self.assertNotIn('集成 NSS', (ROOT / '.github/workflows/MX4200.yml').read_text())

    def test_optional_donor_components_follow_official_defaults(self):
        config = (ROOT / 'user/default/config.diff').read_text().splitlines()
        # Only requested applications, their UI collection and the official
        # hci-uart dependency gate belong in the fragment. Dependencies are
        # selected by real recipes, not an inherited donor package list.
        positive = {line.split('=', 1)[0].removeprefix('CONFIG_PACKAGE_')
                    for line in config if line.startswith('CONFIG_PACKAGE_')
                    and line.endswith('=y')}
        self.assertEqual(positive, {
            'input-support', 'luci', 'autocore', 'luci-app-advanced-reboot',
            'luci-app-aurora-config', 'luci-app-homeproxy', 'luci-app-ttyd',
            'luci-app-wol', 'luci-theme-aurora',
        })
        for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn',
                        'luci-app-attendedsysupgrade'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=n', config)

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
                        'kmod-usb3', 'kmod-usb-storage', 'curl', 'etherwake', 'ttyd'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        for package in ('kmod-bonding', 'proto-bonding', 'kmod-fs-btrfs', 'kmod-fuse',
                        'kmod-wireguard', 'kmod-inet-mptcp-diag', 'kmod-mtd-rw',
                        'kmod-dummy', 'kmod-veth', 'kmod-tcp-bbr',
                        'exfat-fsck', 'exfat-mkfs', 'fdisk', 'gdisk', 'smartmontools',
                        'smartmontools-drivedb', 'iperf3', 'htop', 'ip-full',
                        'openssh-keygen', 'openssh-sftp-server', 'openssl-util',
                        'blkid', 'dmesg', 'lsblk', 'nand-utils', 'xz-utils'):
            for value in ('y', 'm'):
                self.assertNotIn('CONFIG_PACKAGE_' + package + '=' + value, config)
        requested = (ROOT / 'user/default/config.diff').read_text().splitlines()
        for line in requested:
            if line.startswith('CONFIG_PACKAGE_') and line.endswith('=y'):
                self.assertTrue(line in config, line)
        for device in ('mx4200v1', 'mx4200v2'):
            self.assertIn('CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_' + device + '=y', config)
        for package in ('luci-i18n-homeproxy-zh-cn', 'luci-i18n-aurora-config-zh-cn',
                        'luci-i18n-advanced-reboot-zh-cn', 'luci-i18n-wol-zh-cn',
                        'luci-i18n-ttyd-zh-cn', 'sing-box', 'ath11k-firmware-ipq8074',
                        'wpad-openssl', 'kmod-ath11k-ahb'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        self.assertFalse(any(line.startswith('CONFIG_PACKAGE_kmod-qca-nss-') and line.endswith('=y') for line in config))
