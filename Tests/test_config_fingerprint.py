"""Conservative final-config hashing, without changing rolling cache scope."""
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from Tests.test_cache import cache, REF


FINAL = (b'#\n# Automatically generated file; DO NOT EDIT.\n'
         b'# ImmortalWRT Configuration\n#\n'
         b'CONFIG_HAVE_DOT_CONFIG=y\nCONFIG_TARGET_qualcommax=y\n'
         b'CONFIG_PACKAGE_busybox=y\nCONFIG_PACKAGE_example=m\n'
         b'# CONFIG_KERNEL_DEBUG_INFO is not set\n'
         b'CONFIG_VERSION_DIST="ImmortalWrt"\n')


class ConfigFingerprintTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / 'Makefile').write_bytes(b'source\n')
        (self.root / '.config').write_bytes(FINAL)
        real_run = cache.run
        self.enterContext(patch.object(cache, 'run', side_effect=lambda *a, **kw:
            real_run(*a, **kw) if a[0] == 'git' else b'fixed-host\n'))

    def prepare(self, data=FINAL):
        (self.root / '.config').write_bytes(data)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = cache.prepare(self.root, REF, 'fixed-host')
        groups = dict(x.split('=', 1) for x in stderr.getvalue().split()[2:])
        return result, groups

    def test_config_policy_is_versioned_without_rotating_rolling_scope(self):
        before, groups = self.prepare()
        # create=True makes the unchanged implementation fail by equal keys,
        # rather than merely error because the policy constant does not exist.
        with patch.object(cache, 'TC_CONFIG_SCHEMA', 'different-config-policy', create=True):
            after, changed = self.prepare()
        self.assertNotEqual(before['tc-key'], after['tc-key'])
        self.assertEqual(before['rolling-prefix'], after['rolling-prefix'])
        self.assertTrue(before['rolling-prefix'].startswith('mx4200-pax-v2-'))
        self.assertEqual({'environment'}, {k for k in groups if groups[k] != changed[k]})
        self.assertEqual(before['source-files'], after['source-files'])

    def test_unselected_package_comments_and_their_order_are_ignored(self):
        baseline, _ = self.prepare(FINAL +
            b'# CONFIG_PACKAGE_video is not set\n'
            b'# CONFIG_PACKAGE_audio is not set\n')
        reordered = FINAL + (
            b'# CONFIG_PACKAGE_audio is not set\n'
            b'# CONFIG_PACKAGE_video is not set\n'
            b'# CONFIG_PACKAGE_new_unselected is not set\n')
        changed, _ = self.prepare(reordered)
        self.assertEqual(baseline['tc-key'], changed['tc-key'])

    def test_selected_package_state_changes_fingerprint(self):
        baseline, _ = self.prepare(FINAL)
        for old, new in [(b'CONFIG_PACKAGE_example=m', b'CONFIG_PACKAGE_example=y'),
                         (b'CONFIG_PACKAGE_example=m',
                          b'# CONFIG_PACKAGE_example is not set')]:
            with self.subTest(new=new):
                changed, _ = self.prepare(FINAL.replace(old, new))
                self.assertNotEqual(baseline['tc-key'], changed['tc-key'])

    def test_non_package_config_and_values_remain_fingerprint_inputs(self):
        baseline, _ = self.prepare(FINAL)
        changed, _ = self.prepare(FINAL.replace(
            b'CONFIG_TARGET_qualcommax=y', b'CONFIG_TARGET_qualcommax=n'))
        self.assertNotEqual(baseline['tc-key'], changed['tc-key'])
        changed, _ = self.prepare(FINAL.replace(
            b'CONFIG_PACKAGE_example=m', b'CONFIG_PACKAGE_example=n'))
        self.assertNotEqual(baseline['tc-key'], changed['tc-key'])

    def test_malformed_or_ambiguous_package_unset_lines_fall_back_to_raw(self):
        baseline, _ = self.prepare(FINAL + b'# CONFIG_PACKAGE_video is not set\n')
        malformed, _ = self.prepare(FINAL + b'# CONFIG_PACKAGE_video is not set \n')
        self.assertNotEqual(baseline['tc-key'], malformed['tc-key'])
        ambiguous, _ = self.prepare(FINAL +
            b'# CONFIG_PACKAGE_video is not set\n'
            b'# CONFIG_PACKAGE_video is not set\n')
        self.assertNotEqual(baseline['tc-key'], ambiguous['tc-key'])

    def test_fallback_preserves_entire_malformed_or_ambiguous_input(self):
        unset = b'# CONFIG_PACKAGE_unselected is not set\n'
        cases = [
            FINAL.replace(b'CONFIG_HAVE_DOT_CONFIG=y\n', b''),
            FINAL.replace(b'Automatically generated file', b'Config fragment'),
            FINAL + b'CONFIG_PACKAGE_busybox=m\n',
            FINAL + b'# CONFIG_PACKAGE_busybox is not set\n',
            FINAL + unset + unset,
            FINAL + b'CONFIG_PACKAGE_=y\n',
            FINAL + b'# CONFIG_PACKAGE_ is not set\n',
            FINAL + b'CONFIG_VALUE="unterminated\n',
            FINAL + b'CONFIG_VALUE =y\n',
            FINAL + b'# CONFIG_PACKAGE_weird is not set \n',
            FINAL + b'# CONFIG_PACKAGE_weird is not set\r\n',
            FINAL + b'# comment with continuation\\\n',
            FINAL + b'# comment with control\x0b\n',
            FINAL + b'CONFIG_VALUE="line\\\nbreak"\n',
            FINAL.replace(b'\n', b'\r\n'),
            b'CONFIG_PACKAGE_fragment=y\n',
        ]
        for content in cases:
            with self.subTest(content=content):
                data = content + unset
                self.assertEqual(data, cache.config_bytes(data))
        self.assertEqual(FINAL + unset[:-1], cache.config_bytes(FINAL + unset[:-1]))

    def test_kept_bytes_order_mode_and_config_file_are_preserved(self):
        unset = b'# CONFIG_PACKAGE_unselected is not set\n'
        data = FINAL + unset
        self.assertEqual(FINAL, cache.config_bytes(data))
        baseline, groups = self.prepare(data)
        self.assertEqual(data, (self.root / '.config').read_bytes())
        self.assertEqual(cache.EPOCH_NS, (self.root / '.config').stat().st_mtime_ns)
        self.assertEqual((baseline, groups), self.prepare(FINAL))
        changes = [
            FINAL.replace(b'# CONFIG_KERNEL_DEBUG_INFO is not set\n', b''),
            FINAL.replace(b'ImmortalWrt"', b'Other"'),
            FINAL.replace(b'# ImmortalWRT Configuration', b'# Different heading'),
            FINAL + b'\n',
            FINAL.replace(b'CONFIG_PACKAGE_busybox=y\nCONFIG_PACKAGE_example=m\n',
                          b'CONFIG_PACKAGE_example=m\nCONFIG_PACKAGE_busybox=y\n'),
            FINAL + b'CONFIG_PACKAGE_new=y\n',
            FINAL + b'CONFIG_PACKAGE_new=m\n',
            FINAL + b'CONFIG_PACKAGE_new=n\n',
        ]
        for data in changes:
            with self.subTest(data=data):
                changed, after = self.prepare(data)
                self.assertNotEqual(baseline['tc-key'], changed['tc-key'])
                self.assertEqual({'.config'},
                                 {k for k in groups if groups[k] != after[k]})
        (self.root / '.config').chmod(0o600)
        changed, _ = self.prepare()
        self.assertNotEqual(baseline['tc-key'], changed['tc-key'])


if __name__ == '__main__':
    unittest.main()
