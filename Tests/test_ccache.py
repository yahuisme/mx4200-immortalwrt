import os
from pathlib import Path
import subprocess
import tempfile
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/MX4200.yml'


class CcacheTest(unittest.TestCase):
    def test_cold_and_warm_reset_order(self):
        text = WORKFLOW.read_text()
        block = text.split('      - name: Compile firmware\n', 1)[1].split('      - name:', 1)[0]
        script = '\n'.join(line[10:] for line in block.splitlines()[1:])
        for warm in (False, True):
            with self.subTest(warm=warm), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = root / 'staging_dir/host/bin/ccache'
                binary.parent.mkdir(parents=True)
                fixture = root / 'ccache-fixture'
                fixture.write_text('#!/bin/sh\nprintf "ccache %s\\n" "$*" >> "$TRACE"\n')
                fixture.chmod(0o755)
                if warm:
                    binary.write_bytes(fixture.read_bytes())
                    binary.chmod(0o755)
                make = root / 'make'
                make.write_text('#!/bin/sh\nprintf "make %s\\n" "$*" >> "$TRACE"\n'
                                'if [ "$1" = tools/ccache/compile ]; then\n'
                                '  cp "$FIXTURE" staging_dir/host/bin/ccache\nfi\n')
                make.chmod(0o755)
                trace = root / 'trace'
                env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                           TRACE=str(trace), FIXTURE=str(fixture))
                subprocess.run(['bash', '-eu', '-c', script.replace('/mnt/build_wrt', str(root))],
                               env=env, check=True)
                calls = trace.read_text().splitlines()
                self.assertEqual(calls[0].startswith('make tools/ccache/compile'), not warm)
                self.assertEqual(calls[-2], 'ccache --zero-stats')
                self.assertTrue(calls[-1].startswith('make -j'))
                self.assertEqual(len(calls), 2 if warm else 3)


if __name__ == '__main__':
    unittest.main()
