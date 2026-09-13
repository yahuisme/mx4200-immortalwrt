import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GoBootstrapTests(unittest.TestCase):
    def test_workflow_uses_official_external_bootstrap_and_exact_hostpkg(self):
        import yaml
        steps = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']
        setup = [s for s in steps if s.get('uses', '').startswith('actions/setup-go@')]
        self.assertEqual(len(setup), 1)
        self.assertIs(setup[0]['with']['check-latest'], False)
        self.assertIs(setup[0]['with']['cache'], False)
        restore = next(s for s in steps if s['name'] == 'Restore hostpkg cache')
        self.assertNotIn('restore-keys', restore['with'])
        self.assertIn('hostpkg-key', restore['with']['key'])
        by_name = {s['name']: s for s in steps}
        self.assertIn("steps.prune-tc.outcome == 'success'", by_name['Pack hostpkg cache']['if'])
        self.assertIn("steps.prune-hostpkg.outcome == 'success'", by_name['Pack downloads and ccache']['if'])
        self.assertIn('admitted', by_name['Save hostpkg cache']['if'])
        self.assertIn("steps.save-hostpkg.outcome == 'success'", by_name['Prune obsolete hostpkg caches']['if'])
        self.assertLess(steps.index(by_name['Prune obsolete toolchain caches']), steps.index(by_name['Pack hostpkg cache']))
        self.assertLess(steps.index(by_name['Prune obsolete hostpkg caches']), steps.index(by_name['Pack downloads and ccache']))

    def test_official_version_and_reject_ambiguous_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = root / 'feeds/packages/lang/golang/golang-bootstrap/Makefile'
            recipe.parent.mkdir(parents=True)
            for content, expected in [('GO_VERSION_MAJOR_MINOR:=1.24\nGO_VERSION_PATCH:=13\n', True),
                                      ('GO_VERSION_MAJOR_MINOR:=1.24\nGO_VERSION_PATCH:=$(PATCH)\n', False),
                                      ('GO_VERSION_MAJOR_MINOR:=1.24\nGO_VERSION_PATCH:=13\nGO_VERSION_PATCH:=14\n', False)]:
                recipe.write_text(content)
                output = root / 'output'
                output.unlink(missing_ok=True)
                result = subprocess.run(['python3', str(ROOT / 'Scripts/GoBootstrap.py'), str(root)],
                                        env=dict(os.environ, GITHUB_OUTPUT=str(output)), capture_output=True)
                self.assertEqual(result.returncode == 0, expected, result.stderr)
                if expected:
                    self.assertEqual(output.read_text(), 'version=1.24.13\n')
