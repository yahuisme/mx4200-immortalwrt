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
        self.assertLess(workflow.index('id: go-bootstrap'), workflow.index('name: Configure'))
        self.assertLess(workflow.index('CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT='), workflow.index('          make defconfig'))

    def test_package_preparation_keeps_bootstrap_output_and_failures(self):
        import yaml

        workflow = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())
        steps = workflow['jobs']['build']['steps']
        prepare = next(step for step in steps if step.get('id') == 'go-bootstrap')
        setup = next(step for step in steps if step.get('uses', '').startswith('actions/setup-go@'))
        self.assertEqual(prepare['name'], 'Prepare packages')
        self.assertLess(steps.index(prepare), steps.index(setup))
        self.assertNotIn('continue-on-error', prepare)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / 'build'
            (tree / 'scripts').mkdir(parents=True)
            (tree / 'package').mkdir()
            feeds = tree / 'scripts/feeds'
            feeds.write_text('#!/bin/bash\necho "feeds $*" >> "$TRACE"\n')
            feeds.chmod(0o755)
            scripts = root / 'Scripts'
            scripts.mkdir()
            (scripts / 'Packages.sh').write_text(
                'test "$PWD" = "$BUILD/package" || exit 12\n'
                'echo packages >> "$TRACE"\nexit "$PACKAGE_EXIT"\n')
            (scripts / 'GoBootstrap.py').write_bytes((ROOT / 'Scripts/GoBootstrap.py').read_bytes())
            recipe = tree / 'feeds/packages/lang/golang/golang-bootstrap/Makefile'
            recipe.parent.mkdir(parents=True)
            output, trace = root / 'output', root / 'trace'
            for package_exit, valid_version in [('0', True), ('7', True), ('0', False)]:
                with self.subTest(package_exit=package_exit, valid_version=valid_version):
                    recipe.write_text('GO_VERSION_MAJOR_MINOR:=1.26\nGO_VERSION_PATCH:=2\n'
                                      if valid_version else 'GO_VERSION_MAJOR_MINOR:=$(UNKNOWN)\n')
                    output.write_text('')
                    trace.write_text('')
                    env = dict(os.environ, GITHUB_WORKSPACE=str(root), BUILD=str(tree),
                               GITHUB_OUTPUT=str(output), TRACE=str(trace), PACKAGE_EXIT=package_exit)
                    result = subprocess.run(
                        ['bash', '-e', '-o', 'pipefail', '-c',
                         prepare['run'].replace('/mnt/build_wrt', str(tree))],
                        env=env, capture_output=True, text=True)
                    self.assertEqual(trace.read_text().splitlines(),
                                     ['feeds update -a', 'feeds install -a', 'packages'])
                    if package_exit == '0' and valid_version:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(output.read_text(), 'version=1.26.2\n')
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(output.read_text(), '')

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
