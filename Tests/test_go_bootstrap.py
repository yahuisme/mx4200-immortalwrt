import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GoBootstrapTests(unittest.TestCase):
    def test_workflow_uses_native_external_bootstrap(self):
        workflow = (ROOT / '.github/workflows/MX4200.yml').read_text()
        self.assertIn('uses: actions/setup-go@v6', workflow)
        self.assertIn('go-version: ${{ steps.go-bootstrap.outputs.version }}', workflow)
        self.assertIn('cache: false', workflow)
        self.assertIn("echo '# CONFIG_GOLANG_BUILD_BOOTSTRAP is not set' >> .config", workflow)
        self.assertIn('CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT=', workflow)
        self.assertLess(workflow.index('id: go-bootstrap'), workflow.index('name: Configure firmware'))
        self.assertLess(workflow.index('CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT='), workflow.index('          make defconfig'))

    def test_version_comes_from_official_bootstrap_recipe(self):
        script = ROOT / 'Scripts/GoBootstrap.py'
        self.assertTrue(script.exists(), 'official external bootstrap selection missing')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = root / 'feeds/packages/lang/golang/golang-bootstrap/Makefile'
            recipe.parent.mkdir(parents=True)
            output = root / 'output'
            env = dict(os.environ, GITHUB_OUTPUT=str(output))
            for major, patch in [('1.24', '13'), ('1.26', '2')]:
                recipe.write_text(f'GO_VERSION_MAJOR_MINOR:={major}\nGO_VERSION_PATCH:={patch}\n')
                output.write_text('')
                subprocess.run(['python3', str(script), str(root)], env=env, check=True)
                self.assertEqual(output.read_text(), f'version={major}.{patch}\n')
            recipe.write_text('GO_VERSION_MAJOR_MINOR:=$(UNKNOWN)\nGO_VERSION_PATCH:=1\n')
            output.write_text('')
            result = subprocess.run(['python3', str(script), str(root)], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), '')


if __name__ == '__main__':
    unittest.main()
