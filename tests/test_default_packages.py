"""Per-device defaults must be available, including virtual providers."""
import os
from pathlib import Path
import re
import unittest
from scripts.check_defaults import check


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

    def test_explicit_recipe_packages_and_exclusions(self):
        requested = (Path(__file__).resolve().parents[1] / 'user/default/config.diff').read_text()
        config = 'CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=m\n' + requested
        check(config, '', requested)
        for package, wanted in re.findall(r'^CONFIG_PACKAGE_([^=]+)=([yn])$', requested, re.M):
            for actual in ('m', 'n', '') if wanted == 'y' else ('y', 'm'):
                with self.subTest(package=package, actual=actual):
                    broken = config.replace(f'CONFIG_PACKAGE_{package}={wanted}',
                                            f'CONFIG_PACKAGE_{package}={actual}' if actual else '')
                    with self.assertRaisesRegex(ValueError, re.escape(package)):
                        check(broken, '', requested)
        disabled = re.sub(r'^CONFIG_PACKAGE_([^=]+)=n$', r'# CONFIG_PACKAGE_\1 is not set', config, flags=re.M)
        check(disabled, '', requested)
        absent = re.sub(r'^CONFIG_PACKAGE_([^=]+)=n$', '', config, flags=re.M)
        check(absent, '', requested)

    def test_explicit_non_package_recipe_symbols_survive_defconfig(self):
        requested = (Path(__file__).resolve().parents[1] / 'user/default/config.diff').read_text()
        config = 'CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=m\n' + requested
        check(config, '', requested)
        rows = re.findall(r'^CONFIG_(?!PACKAGE_)([^=]+)=(.*)$', requested, re.M)
        rows += [(symbol, 'n') for symbol in re.findall(
            r'^# CONFIG_(?!PACKAGE_)(\S+) is not set$', requested, re.M)]
        for symbol, wanted in rows:
            original = (f'# CONFIG_{symbol} is not set' if
                        f'# CONFIG_{symbol} is not set' in requested else f'CONFIG_{symbol}={wanted}')
            for actual in (('m', 'n', '') if wanted == 'y' else
                           ('y', 'm') if wanted == 'n' else ('"wrong"', '')):
                with self.subTest(symbol=symbol, wanted=wanted, actual=actual):
                    broken = config.replace(original, f'CONFIG_{symbol}={actual}' if actual else '')
                    with self.assertRaisesRegex(ValueError, re.escape(symbol)):
                        check(broken, '', requested)
            if wanted == 'n':
                check(config.replace(original, f'# CONFIG_{symbol} is not set'), '', requested)
                check(config.replace(original, ''), '', requested)

    def test_requested_module_and_commented_package_exclusion(self):
        config = ('CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=m\n'
                  'CONFIG_PACKAGE_optional=m\n')
        requested = 'CONFIG_PACKAGE_optional=m\n# CONFIG_PACKAGE_excluded is not set\n'
        check(config, '', requested)
        for actual in ('y', 'n', ''):
            with self.subTest(actual=actual), self.assertRaisesRegex(ValueError, 'optional'):
                check(config.replace('CONFIG_PACKAGE_optional=m',
                                     f'CONFIG_PACKAGE_optional={actual}' if actual else ''), '', requested)
        with self.assertRaisesRegex(ValueError, 'excluded'):
            check(config + 'CONFIG_PACKAGE_excluded=m\n', '', requested)

    def test_usteer_is_rejected_without_recipe_exclusions(self):
        # Package policy is checked on the resolved config, not on optional
        # historical '=n' lines in config.diff. Both built-in and module fail.
        for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn'):
            for value in ('y', 'm'):
                with self.subTest(package=package, value=value):
                    config = ('CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=m\n'
                              f'CONFIG_PACKAGE_{package}={value}\n')
                    with self.assertRaisesRegex(ValueError, re.escape(package)):
                        check(config, '', '')
        check('CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=m\n', '', '')

    def test_retired_proxy_packages_are_rejected(self):
        for package in ('luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box',
                        'honk', 'honk-go', 'luci-app-honk', 'luci-lib-daeuniverse',
                        'luci-i18n-daeuniverse-zh-cn'):
            for value in ('y', 'm'):
                with self.subTest(package=package, value=value):
                    config = ('CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=m\n'
                              f'CONFIG_PACKAGE_{package}={value}\n')
                    with self.assertRaisesRegex(ValueError, re.escape(package)):
                        check(config, '', '')

    def test_formal_workflow_runs_gate_with_recipe(self):
        import subprocess
        import tempfile
        import yaml
        root = Path(__file__).resolve().parents[1]
        steps = yaml.safe_load((root / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']
        code = next(s['run'] for s in steps if s['name'] == 'Prepare source and cache key')
        command = next(line for line in code.splitlines() if '/cache-scripts/check_defaults.py' in line)
        self.assertLess(code.index('make defconfig'), code.index(command))
        self.assertLess(code.index(command), code.index('/cache-scripts/cache.py'))
        command = command.replace('/cache-scripts/', str(root / 'scripts') + '/')
        requested = (root / 'user/default/config.diff').read_text()
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            (build / 'tmp').mkdir()
            (build / 'tmp/.packageinfo').write_text('')
            config = 'CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=m\n' + requested
            for fault in ('', 'missing-app', 'excluded-module', 'retired-proxy', 'missing-v2',
                          'missing-rootfs', 'missing-ip-full', 'missing-dummy',
                          'missing-tproxy', 'embedded-btf'):
                broken = config
                if fault == 'missing-app':
                    broken = broken.replace('CONFIG_PACKAGE_luci-app-ttyd=y', '')
                if fault == 'excluded-module':
                    broken += '\nCONFIG_PACKAGE_usteer=m\n'
                    self.assertNotEqual(broken, config)
                if fault == 'retired-proxy':
                    broken += '\nCONFIG_PACKAGE_honk=m\n'
                    self.assertNotEqual(broken, config)
                for name, symbol in (
                        ('missing-v2', 'TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v2'),
                        ('missing-rootfs', 'TARGET_PER_DEVICE_ROOTFS'),
                        ('missing-ip-full', 'PACKAGE_ip-full'),
                        ('missing-dummy', 'PACKAGE_kmod-dummy'),
                        ('missing-tproxy', 'PACKAGE_kmod-nft-tproxy')):
                    if fault == name:
                        broken = broken.replace(f'CONFIG_{symbol}=y', '')
                        self.assertNotEqual(broken, config)
                if fault == 'embedded-btf':
                    broken = broken.replace('# CONFIG_KERNEL_DEBUG_INFO_BTF is not set',
                                            'CONFIG_KERNEL_DEBUG_INFO_BTF=y')
                    self.assertNotEqual(broken, config)
                (build / '.config').write_text(broken)
                result = subprocess.run(['bash', '-ec', command], cwd=build,
                                        env=dict(os.environ, DK_PROFILE=str(root / 'user/default')),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not fault, f'{fault}: {result.stderr}')

    def test_empty_config_fails(self):
        with self.assertRaisesRegex(ValueError, 'no enabled MODULE_DEFAULT'):
            check('', '')

    @unittest.skipUnless(os.environ.get('MX4200_PREPARED_SOURCE'), 'set MX4200_PREPARED_SOURCE')
    def test_real_both_device_defaults_and_dependency_regression(self):
        source = Path(os.environ['MX4200_PREPARED_SOURCE'])
        config = (source / '.config').read_text()
        metadata = (source / 'tmp/.packageinfo').read_text()
        defaults = set(check(config, metadata, (Path(__file__).resolve().parents[1] / 'user/default/config.diff').read_text()))
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
