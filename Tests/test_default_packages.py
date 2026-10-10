"""Per-device defaults must be available, including virtual providers."""
import os
from pathlib import Path
import re
import unittest
from Scripts.CheckDefaults import check


class DefaultPackageTests(unittest.TestCase):
    def test_missing_and_disabled_defaults_fail(self):
        for value in ('', 'CONFIG_PACKAGE_kmod-hci-uart=n\n', '# CONFIG_PACKAGE_kmod-hci-uart is not set\n'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'kmod-hci-uart'):
                check('CONFIG_MODULE_DEFAULT_kmod-hci-uart=y\n' + value, '')

    def test_y_and_m_satisfy_defaults(self):
        for value in ('y', 'm'):
            self.assertEqual(check('CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=' + value, ''), ['driver'])

    def test_virtual_default_requires_selected_provider(self):
        metadata = 'Package: nftables-json\nProvides: @nftables-json-any nftables\n'
        config = 'CONFIG_MODULE_DEFAULT_nftables=y\n'
        with self.assertRaisesRegex(ValueError, 'nftables'):
            check(config, metadata)
        self.assertEqual(check(config + 'CONFIG_PACKAGE_nftables-json=y\n', metadata), ['nftables'])

    def test_empty_config_fails(self):
        with self.assertRaisesRegex(ValueError, 'no enabled MODULE_DEFAULT'):
            check('', '')

    @unittest.skipUnless(os.environ.get('MX4200_PREPARED_SOURCE'), 'set MX4200_PREPARED_SOURCE')
    def test_real_both_device_defaults_and_dependency_regression(self):
        source = Path(os.environ['MX4200_PREPARED_SOURCE'])
        config = (source / '.config').read_text()
        metadata = (source / 'tmp/.packageinfo').read_text()
        defaults = set(check(config, metadata))
        targets = (source / 'tmp/.config-target.in').read_text()
        for device in ('mx4200v1', 'mx4200v2'):
            symbol = 'TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_' + device
            self.assertIn('CONFIG_' + symbol + '=y', config)
            match = re.search(r'^(?:menu)?config ' + symbol + r'\n(.*?)(?=^(?:menu)?config |\Z)', targets, re.M | re.S)
            assert match is not None, symbol
            block = match.group(1)
            required = set(re.findall(r'select MODULE_DEFAULT_(\S+)', block))
            self.assertTrue(required)
            self.assertLessEqual(required, defaults)
        for package in ('kmod-hci-uart', 'kmod-bluetooth', 'kmod-hid', 'kmod-input-core', 'kmod-input-evdev'):
            self.assertRegex(config, r'(?m)^CONFIG_PACKAGE_' + package + r'=[ym]$')
        broken = re.sub(r'^CONFIG_PACKAGE_kmod-hci-uart=[ym]$', '# CONFIG_PACKAGE_kmod-hci-uart is not set', config, flags=re.M)
        with self.assertRaisesRegex(ValueError, 'kmod-hci-uart'):
            check(broken, metadata)
