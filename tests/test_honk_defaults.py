"""Real official core, mock datapath, private loopback network only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HonkDefaultsTests(unittest.TestCase):
    def test_official_core_serves_authenticated_embedded_ui_in_private_netns(self):
        fixture = os.environ.get('MX_APK_RUNTIME_FIXTURE')
        self.assertTrue(fixture, 'set MX_APK_RUNTIME_FIXTURE')
        assert fixture
        fixture = Path(fixture)
        config = ROOT / 'user/default/files/etc/honk/config.dae'
        self.assertTrue(config.is_file(), 'firmware must include a usable Honk default')
        source = config.read_text()
        self.assertIn("listen: '192.168.10.1:9527'", source)
        self.assertNotIn('allow_anonymous_loopback: true', source)
        self.assertIn('password_auth: true', source)
        self.assertIn('config_write: true', source)
        self.assertIn("ui: 'embedded'", source)
        self.assertIn("data_dir: '/etc/honk/data'", source)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'config.dae').write_text(source.replace('/etc/honk/data', tmp + '/data'))
            root = fixture / 'mx4200-root'
            command = [str(root / 'lib/ld-musl-aarch64.so.1'), '--library-path',
                       str(root / 'lib') + ':' + str(root / 'usr/lib'), str(root / 'usr/bin/honk-core'),
                       '--mock-ebpf', '--config', str(path / 'config.dae')]
            script = '''import json,subprocess,time,urllib.request,urllib.error,sys
from pathlib import Path
command=json.loads(sys.argv[1]); root=Path(sys.argv[2])
subprocess.run(['ip','link','set','lo','up'],check=True)
subprocess.run(['ip','addr','add','192.168.10.1/32','dev','lo'],check=True)
with (root/'core.log').open('w') as log:
 p=subprocess.Popen(command,stdout=log,stderr=log)
 try:
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  for attempt in range(80):
   if p.poll() is not None: raise RuntimeError((root/'core.log').read_text())
   try:
    body=opener.open('http://192.168.10.1:9527/ui/',timeout=.2).read()
    break
   except (OSError,urllib.error.URLError): time.sleep(.1)
  else: raise RuntimeError((root/'core.log').read_text())
  assert b'<html' in body.lower(),body[:200]
  try: opener.open('http://192.168.10.1:9527/api/v1/runtime',timeout=1)
  except urllib.error.HTTPError as e: assert e.code==401,e.code
  else: raise AssertionError('private runtime API is anonymously accessible')
  print('embedded UI ready; runtime API returns 401; mock datapath only')
 finally:
  p.terminate()
  try:p.wait(timeout=8)
  except subprocess.TimeoutExpired:p.kill();p.wait()
'''
            result = subprocess.run(['unshare', '--net', '--mount', '--fork', 'python3', '-c', script,
                                     json.dumps(command), tmp], capture_output=True, text=True, timeout=35)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('runtime API returns 401', result.stdout)


if __name__ == '__main__':
    unittest.main()
