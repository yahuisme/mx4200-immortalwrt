"""Firmware input identity and release gate regressions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InputTests(unittest.TestCase):
    def test_fingerprints_track_only_consumed_content(self):
        spec = importlib.util.spec_from_file_location('Inputs', ROOT/'Scripts/Inputs.py')
        self.assertTrue((ROOT/'Scripts/Inputs.py').is_file(), 'Missing firmware input fingerprint producer')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            for name in ('Config/MX4200.txt', 'files/etc/default', 'Scripts/Settings.sh', 'package/nss/Makefile', 'patches/a.patch', '.github/workflows/MX4200.yml'):
                f = p/name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text('input\n')
            initial = module.local_fingerprint(p)
            (p/'README.md').write_text('docs only')
            (p/'.github/workflows/MX4200.yml').write_text('workflow only\n')
            self.assertEqual(module.local_fingerprint(p), initial)
            (p/'.github/workflows/MX4200.yml').write_text('      WRT_SSID: changed\n')
            self.assertNotEqual(module.local_fingerprint(p), initial)
            (p/'files/etc/default').write_text('changed')
            self.assertNotEqual(module.local_fingerprint(p), initial)
            subprocess.run(['git', 'init', '-q', str(p)], check=True)
            for name in ('luci-app-homeproxy', 'sing-box', 'unconsumed'):
                (p/name).mkdir()
                (p/name/'Makefile').write_text(name)
            subprocess.run(['git', '-C', str(p), 'add', '.'], check=True)
            before = module.package_fingerprint(p, ('luci-app-homeproxy', 'sing-box'))
            (p/'unconsumed/Makefile').write_text('changed')
            (p/'README.md').write_text('new docs')
            subprocess.run(['git', '-C', str(p), 'add', '.'], check=True)
            self.assertEqual(module.package_fingerprint(p, ('luci-app-homeproxy', 'sing-box')), before)
            (p/'sing-box/Makefile').write_text('changed')
            subprocess.run(['git', '-C', str(p), 'add', '.'], check=True)
            self.assertNotEqual(module.package_fingerprint(p, ('luci-app-homeproxy', 'sing-box')), before)

    def test_workflow_produces_and_publishes_actual_identity(self):
        workflow = (ROOT/'.github/workflows/MX4200.yml').read_text()
        self.assertIn('python3 Scripts/Inputs.py --probe /mnt/build_wrt/source-lock.json', workflow)
        self.assertIn('Firmware inputs: `{d["firmware_inputs_sha256"]}`', workflow)
        packages = (ROOT/'Scripts/Packages.sh').read_text()
        self.assertIn('record(data,', packages)

    def test_release_gate_includes_firmware_inputs(self):
        # Execute the actual workflow comparison, as in the audit reproduction.
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())
        block = next(s['run'] for s in workflow['jobs']['check']['steps'] if s.get('id') == 'compare')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            current = dict(official_commit='a'*40, donor_commit='b'*40, firmware_inputs_sha256='c'*64)
            (p/'source-lock.json').write_text(json.dumps(current))
            gh = p/'gh'
            gh.write_text('#!/bin/sh\nprintf "%s\\n" "$RELEASE_BODY"\n')
            gh.chmod(0o755)
            block = block.replace('/mnt/build_wrt/source-lock.json', str(p/'source-lock.json'))
            base = '官方 ImmortalWrt v1: `' + 'a'*40 + '`\nLiBwrt NSS v1: `' + 'b'*40 + '`\n'
            for digest, expected in [(None, 'true'), ('c'*64, 'false'), ('d'*64, 'true')]:
                body = base + (f'Firmware inputs: `{digest}`\n' if digest else '')
                result = subprocess.run(['bash', '-e', '-c', block], cwd=ROOT, env=dict(os.environ, PATH=str(p)+':'+os.environ['PATH'], GITHUB_EVENT_NAME='schedule', GITHUB_REPOSITORY='fixture/test', GITHUB_OUTPUT=str(p/'output'), RELEASE_BODY=body), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('changed='+expected, (p/'output').read_text())
            (p/'source-lock.json').unlink()
            (p/'output').write_text('')
            result = subprocess.run(['bash', '-e', '-c', block], cwd=ROOT, env=dict(os.environ, GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_OUTPUT=str(p/'output')), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((p/'output').read_text(), 'changed=true\n')


if __name__ == '__main__':
    unittest.main()
