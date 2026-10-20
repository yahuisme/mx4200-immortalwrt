"""External bootstrap stays in Docker; official feed floor is fail closed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class GoBootstrapTests(unittest.TestCase):
    def test_workflow_uses_pinned_docker_external_bootstrap(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())
        steps = workflow['jobs']['build']['steps']
        self.assertFalse(any(s.get('uses','').startswith('actions/setup-go@') for s in steps))
        self.assertFalse(any('hostpkg' in s['name'].lower() for s in steps))
        config = (ROOT / 'user/default/config.diff').read_text()
        self.assertIn('CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT="/usr/lib/go"', config)
        self.assertIn('# CONFIG_GOLANG_BUILD_BOOTSTRAP is not set', config)
        source = next(s['run'] for s in steps if s['name']=='Prepare source and cache key')
        self.assertIn('python3 /cache-scripts/check_go.py "$DK_OPENWRT" /usr/lib/go', source)
        self.assertLess(source.index('check_go.py'), source.index('make defconfig'))

    def test_official_floor_and_reject_ambiguous_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            recipe=root/'feeds/packages/lang/golang/golang-bootstrap/Makefile'
            recipe.parent.mkdir(parents=True)
            go=root/'bootstrap/bin/go'; go.parent.mkdir(parents=True)
            for floor, actual, valid in [
                ('1.24.6','1.26.8',True), ('1.26.8','1.26.8',True),
                ('1.26.9','1.26.8',False), ('1.27.0','1.26.8',False),
                ('1.24.$(PATCH)','1.26.8',False), ('1.24.6','1.26rc1',False),
            ]:
                major,minor,patch=floor.split('.')
                recipe.write_text(f'GO_VERSION_MAJOR_MINOR:={major}.{minor}\nGO_VERSION_PATCH:={patch}\n')
                go.write_text(f'#!/bin/sh\n[ "$GOTOOLCHAIN" = local ] || exit 9\necho "go version go{actual} linux/arm64"\n')
                go.chmod(0o755)
                result=subprocess.run(['python3',str(ROOT/'scripts/check_go.py'),str(root),str(root/'bootstrap')],capture_output=True,text=True)
                self.assertEqual(result.returncode==0,valid,result.stderr)
            recipe.write_text('GO_VERSION_MAJOR_MINOR:=1.24\nGO_VERSION_PATCH:=6\nGO_VERSION_PATCH:=7\n')
            result=subprocess.run(['python3',str(ROOT/'scripts/check_go.py'),str(root),str(root/'bootstrap')],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
