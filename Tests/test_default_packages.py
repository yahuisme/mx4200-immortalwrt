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

    def test_explicit_recipe_packages_and_exclusions(self):
        requested = (Path(__file__).resolve().parents[1] / 'Config/MX4200.txt').read_text()
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

    def test_formal_workflow_runs_gate_with_recipe(self):
        import subprocess
        import tempfile
        import yaml
        root = Path(__file__).resolve().parents[1]
        steps = yaml.safe_load((root / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']
        code = next(s['run'] for s in steps if s['name'] == 'Configure firmware and caches')
        command = next(line for line in code.splitlines() if 'Scripts/CheckDefaults.py' in line)
        self.assertLess(code.index('make defconfig'), code.index(command))
        self.assertLess(code.index(command), code.index('Scripts/Cache.py'))
        requested = (root / 'Config/MX4200.txt').read_text()
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            (build / 'tmp').mkdir()
            (build / 'tmp/.packageinfo').write_text('')
            config = 'CONFIG_MODULE_DEFAULT_driver=y\nCONFIG_PACKAGE_driver=m\n' + requested
            for fault in ('', 'missing-app', 'excluded-module'):
                broken = config
                if fault == 'missing-app':
                    broken = broken.replace('CONFIG_PACKAGE_luci-app-homeproxy=y', '')
                if fault == 'excluded-module':
                    broken = broken.replace('CONFIG_PACKAGE_usteer=n', 'CONFIG_PACKAGE_usteer=m')
                (build / '.config').write_text(broken)
                result = subprocess.run(['bash', '-ec', command], cwd=build,
                                        env=dict(os.environ, GITHUB_WORKSPACE=str(root)),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not fault, result.stderr)

    def test_empty_config_fails(self):
        with self.assertRaisesRegex(ValueError, 'no enabled MODULE_DEFAULT'):
            check('', '')

    @unittest.skipUnless(os.environ.get('MX4200_PREPARED_SOURCE'), 'set MX4200_PREPARED_SOURCE')
    def test_real_both_device_defaults_and_dependency_regression(self):
        source = Path(os.environ['MX4200_PREPARED_SOURCE'])
        config = (source / '.config').read_text()
        metadata = (source / 'tmp/.packageinfo').read_text()
        defaults = set(check(config, metadata, (Path(__file__).resolve().parents[1] / 'Config/MX4200.txt').read_text()))
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
