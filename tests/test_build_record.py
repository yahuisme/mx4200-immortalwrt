"""Source provenance failures retain diagnostics without authorizing publication."""
import json
from pathlib import Path
import tempfile
import unittest
import test_record_contract as records


class SourceProvenanceTests(unittest.TestCase):
    def test_missing_malformed_or_unexpected_identity_is_rejected(self):
        helper = records.RecordContract()
        for value in (None, '', 'invalid',
                      'yahuisme/packages\thttps://example.invalid/other\t' + 'a' * 40,
                      'other\thttps://github.com/yahuisme/packages.git\t' + 'a' * 40,
                      'yahuisme/packages\thttps://github.com/yahuisme/packages.git\tbad',
                      'yahuisme/packages\thttps://github.com/yahuisme/packages.git\t' + 'a' * 40 + '\nextra'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                helper.fixture(base)
                log = base / '.custom-revisions.tsv'
                if value is None:
                    log.unlink()
                else:
                    log.write_text(value)
                result = helper.run_record(base)
                self.assertNotEqual(result.returncode, 0)
                record = json.loads((base / 'record/build.json').read_text())
                self.assertEqual(record['custom_sources'], [])
                self.assertTrue(record['source'])
                self.assertTrue(record['external_packages'])
                errors = json.loads((base / 'record/diagnostics.json').read_text())['errors']
                self.assertTrue(any('Custom package provenance invalid:' in error for error in errors))
