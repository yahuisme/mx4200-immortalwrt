"""Official snapshot defaults and intentional customization requirements."""
import os
from pathlib import Path
import unittest
import yaml
from Scripts.CheckDefaults import check

ROOT = Path(__file__).resolve().parents[1]


class OfficialMigrationTests(unittest.TestCase):
    def test_official_source_and_release_description(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())
        env = workflow['jobs']['build']['env']
        self.assertEqual(env['WRT_REPO'], 'https://github.com/immortalwrt/immortalwrt.git')
        self.assertEqual(env['WRT_BRANCH'], 'master')
        self.assertNotIn('集成 NSS', (ROOT / '.github/workflows/MX4200.yml').read_text())

    def test_optional_donor_components_follow_official_defaults(self):
        config = (ROOT / 'Config/MX4200.txt').read_text().splitlines()
        for package in ('e2fsprogs', 'f2fs-tools', 'kmod-fs-ext4', 'kmod-fs-f2fs',
                        'wpad-openssl', 'usbutils'):
            self.assertFalse(any(line.startswith('CONFIG_PACKAGE_' + package + '=')
                                 for line in config), package)
        for package in ('kmod-usb3', 'kmod-usb-core', 'kmod-usb-dwc3',
                        'kmod-usb-storage', 'kmod-usb-storage-extras',
                        'kmod-usb-storage-uas', 'automount', 'input-support'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)

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
        self.assertIn('CONFIG_PACKAGE_luci-app-package-manager=y', config)
        requested = (ROOT / 'Config/MX4200.txt').read_text().splitlines()
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
