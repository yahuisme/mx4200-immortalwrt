import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DownloadCacheTests(unittest.TestCase):
    def test_workflow_gates_final_contents_and_cache_miss(self):
        workflow = (ROOT / '.github/workflows/MX4200.yml').read_text()
        self.assertIn("steps.downloads-after.outputs.files != '0'", workflow)
        self.assertIn("steps.downloads.outputs.cache-matched-key == '' || steps.downloads-before.outputs.digest != steps.downloads-after.outputs.digest", workflow)
        self.assertLess(workflow.index('id: downloads-before'), workflow.index('name: Download packages'))
        self.assertLess(workflow.index('name: Compile firmware'), workflow.index('id: downloads-after'))
        self.assertLess(workflow.index('id: downloads-after'), workflow.index('name: Save cache'))

    def test_content_not_timestamp_controls_save(self):
        script = ROOT / 'Scripts/Downloads.py'
        self.assertTrue(script.exists(), 'download content gate missing')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dl = root / 'dl'
            output = root / 'output'
            def snapshot():
                output.write_text('')
                subprocess.run(['python3', str(script), str(dl)], check=True,
                               env=dict(os.environ, GITHUB_OUTPUT=str(output)))
                return dict(line.split('=', 1) for line in output.read_text().splitlines())
            self.assertEqual(snapshot()['files'], '0')
            dl.mkdir()
            archive = dl / 'source.tar.gz'
            archive.write_bytes(b'first')
            first = snapshot()
            os.utime(archive, None)
            self.assertEqual(snapshot(), first)
            archive.write_bytes(b'other')
            self.assertNotEqual(snapshot()['digest'], first['digest'])
            archive.write_bytes(b'first')
            nested = dl / 'go-mod-cache/cache/download/example/@v'
            nested.mkdir(parents=True)
            (nested / 'v1.zip').write_bytes(b'module')
            self.assertNotEqual(snapshot()['digest'], first['digest'])
            (nested / 'v1.zip').unlink()
            self.assertEqual(snapshot(), first)
            archive.rename(dl / 'renamed.tar.gz')
            self.assertNotEqual(snapshot()['digest'], first['digest'])


if __name__ == '__main__':
    unittest.main()
