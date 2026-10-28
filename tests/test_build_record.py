"""Package preparation delegates to the external signed-APK boundary; no build."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagePreparationTests(unittest.TestCase):
    def test_packages_delegates_prepare_and_propagates_failure(self):
        original = (ROOT / 'scripts/packages.sh').read_text()
        self.assertNotIn('git clone', original)
        self.assertNotIn('.custom-revisions.tsv', original)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / 'source/package'
            package.mkdir(parents=True)
            hook = root / 'external_packages.py'
            hook.write_text('''import json, os, sys
from pathlib import Path
Path(os.environ['CALLS']).write_text(json.dumps([sys.argv[1:], str(Path.cwd())]))
sys.exit(int(os.environ['STATUS']))
''')
            # Relocate only the fixed container mount; production arguments stay intact.
            script = root / 'packages.sh'
            script.write_text(original.replace('/cache-scripts/external_packages.py', str(hook)))
            for status in (0, 19):
                with self.subTest(status=status):
                    result = subprocess.run(['bash', str(script)], cwd=package,
                        env=dict(os.environ, CALLS=str(root / 'calls'), STATUS=str(status)),
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode, status, result.stderr)
                    args, cwd = json.loads((root / 'calls').read_text())
                    self.assertEqual(args, ['prepare', '..'])
                    self.assertEqual(cwd, str(package))
                    self.assertEqual(list(package.iterdir()), [])
                    self.assertFalse((package.parent / '.custom-revisions.tsv').exists())
