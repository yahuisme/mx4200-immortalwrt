"""Exercise local preferences after the signed package's Aurora initialization."""
from pathlib import Path
import tempfile
import unittest

from test_runtime_defaults import DefaultsFixture


class AuroraDefaultsTests(unittest.TestCase):
    def fixture(self, tmp):
        fixture = DefaultsFixture(Path(tmp), '99-mx4200-aurora')
        self.assertGreater(fixture.script.name, '80_aurora')
        return fixture

    def test_only_two_preferences_change_in_native_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.fixture(tmp)
            before = fixture.uci('show', 'aurora')
            fixture.boot()
            self.assertFalse(fixture.script.exists())
            self.assertEqual(fixture.uci('show', 'aurora'), before.replace("'mega-menu'", "'sidebar'").replace("'0.5rem'", "'0.125rem'"))

    def test_retained_upgrade_is_untouched(self):
        for retained in ('sysupgrade.tgz', 'tmp/sysupgrade.tar'):
            with self.subTest(retained=retained), tempfile.TemporaryDirectory() as tmp:
                fixture = self.fixture(tmp)
                (fixture.root / retained).touch()
                before = fixture.snapshot()
                fixture.boot()
                self.assertEqual(fixture.snapshot(), before)
                self.assertFalse(fixture.script.exists())
                self.assertEqual((fixture.root / 'calls').read_text().splitlines(), ['commit'])

    def test_missing_or_unknown_schema_and_failed_writes_never_change_later_config(self):
        cases = (("config unknown 'theme'\n", {}), ("config aurora 'theme'\n", {}),
                 ('', {}), (None, {'fail': 'aurora.theme.nav_type'}),
                 (None, {'fail': 'aurora.theme.struct_radius_base'}), (None, {'fail_commit': 'aurora'}),
                 (None, {'fail_publish': 'aurora'}))
        for config, fault in cases:
            with self.subTest(config=config, fault=fault), tempfile.TemporaryDirectory() as tmp:
                fixture = self.fixture(tmp)
                known = (fixture.cfg / 'aurora').read_text()
                if config is not None:
                    fixture.set_files({'aurora': config})
                before = fixture.snapshot()
                fixture.boot(**fault)
                self.assertTrue(fixture.script.exists())
                self.assertEqual(fixture.snapshot(), before)
                fixture.set_files({'aurora': known.replace('mega-menu', 'personal')})
                before = fixture.snapshot()
                fixture.boot()
                self.assertFalse(fixture.script.exists())
                self.assertEqual(fixture.snapshot(), before)
