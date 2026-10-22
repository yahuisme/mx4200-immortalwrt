"""The fragment carries intent; dependency and exclusion gates check final state."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'user/default/config.diff'
USTEER = ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn')


class ProfileConfigurationTests(unittest.TestCase):
    def test_usteer_has_no_redundant_negative_profile_records(self):
        symbols = set(re.findall(r'^(?:# )?CONFIG_([^= ]+)', PROFILE.read_text(), re.M))
        for package in USTEER:
            self.assertNotIn('PACKAGE_' + package, symbols)

    def test_keep_official_dependency_gate_and_meaningful_exclusions(self):
        lines = set(PROFILE.read_text().splitlines())
        for symbol in ('TARGET_MULTI_PROFILE',
                       'TARGET_PER_DEVICE_ROOTFS',
                       'TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v1',
                       'TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_mx4200v2'):
            self.assertIn('CONFIG_' + symbol + '=y', lines)
        for symbol in ('TARGET_ROOTFS_INITRAMFS', 'FEED_video',
                       'PACKAGE_luci-app-attendedsysupgrade'):
            self.assertIn('CONFIG_' + symbol + '=n', lines)

    @unittest.skipUnless(os.environ.get('PROFILE_KCONFIG_SOURCE') and
                         os.environ.get('PROFILE_KCONFIG_OLD_FRAGMENT'),
                         'set official prepared source and pre-cleanup fragment')
    def test_real_kconfig_final_config_is_byte_identical(self):
        source = Path(os.environ['PROFILE_KCONFIG_SOURCE'])
        old = Path(os.environ['PROFILE_KCONFIG_OLD_FRAGMENT'])
        with tempfile.TemporaryDirectory() as directory:
            results = []
            for name, fragment in (('old', old), ('new', PROFILE)):
                requested = Path(directory) / (name + '.diff')
                requested.write_text(fragment.read_text() + '\nCONFIG_CCACHE_DIR="/ghcache"\n')
                output = Path(directory) / (name + '.config')
                # Kconfig's hostcxx capability probe normally compiles a
                # test. Point it at an empty staging path: no compiler runs.
                env = dict(os.environ, KCONFIG_CONFIG=str(output),
                           STAGING_DIR_HOST=str(Path(directory) / 'no-build-host'))
                result = subprocess.run([str(source / 'scripts/config/conf'),
                                         '--defconfig=' + str(requested), 'Config.in'],
                                        cwd=source, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                results.append(output.read_bytes())
            self.assertEqual(results[0], results[1])
            text = results[1].decode()
            for package in USTEER:
                self.assertNotRegex(text, rf'(?m)^CONFIG_PACKAGE_{package}=[ym]$')
