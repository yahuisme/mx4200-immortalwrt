"""Execute complete workflow shell blocks with offline command fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/MX4200.yml'


class CcacheTest(unittest.TestCase):
    def test_compile_and_statistics_control_flow(self):
        steps = {s.get('name'): s for s in yaml.safe_load(WORKFLOW.read_text())['jobs']['build']['steps']}
        self.assertEqual(steps['Cache statistics']['if'], 'always()')
        # warm, bootstrap failure, parallel failure, serial failure, stats failure
        cases = [(False, 0, 0, 0, 0), (True, 0, 0, 0, 0),
                 (False, 7, 0, 0, 0), (True, 0, 8, 0, 0),
                 (True, 0, 8, 9, 0), (True, 0, 8, 9, 6)]
        for warm, bootstrap, parallel, serial, stats in cases:
            with self.subTest(case=(warm, bootstrap, parallel, serial, stats)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                binary = root / 'staging_dir/host/bin/ccache'
                binary.parent.mkdir(parents=True)
                fixture = root / 'ccache-fixture'
                fixture.write_text('#!/bin/sh\nprintf "ccache %s cap=%s\\n" "$*" "$CCACHE_MAXSIZE" >> "$TRACE"\n'
                                   'if [ "$1" = --show-stats ]; then exit "$STATS"; fi\n')
                fixture.chmod(0o755)
                if warm:
                    binary.write_bytes(fixture.read_bytes())
                    binary.chmod(0o755)
                make = root / 'make'
                make.write_text('#!/bin/sh\nprintf "make %s\\n" "$*" >> "$TRACE"\n'
                                'if [ "$1" = tools/ccache/compile ]; then\n'
                                '  [ "$BOOTSTRAP" = 0 ] || exit "$BOOTSTRAP"\n'
                                '  cp "$FIXTURE" staging_dir/host/bin/ccache\n'
                                'elif [ "$1" = -j1 ]; then exit "$SERIAL"\n'
                                'else exit "$PARALLEL"; fi\n')
                make.chmod(0o755)
                nproc = root / 'nproc'
                nproc.write_text('#!/bin/sh\nprintf "4\\n"\n')
                nproc.chmod(0o755)
                trace = root / 'trace'
                env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                           TRACE=str(trace), FIXTURE=str(fixture), BOOTSTRAP=str(bootstrap),
                           PARALLEL=str(parallel), SERIAL=str(serial), STATS=str(stats))
                def run(name):
                    return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c',
                                           steps[name]['run'].replace('/mnt/build_wrt', str(root))],
                                          env=env, capture_output=True, text=True)
                result = run('Compile firmware')
                self.assertEqual(result.returncode, bootstrap or (serial if parallel else 0), result.stderr)
                expected = [] if warm else ['make tools/ccache/compile -j4 V=s']
                if not bootstrap:
                    expected += ['ccache --zero-stats cap=2G', 'make -j4 V=s']
                    if parallel:
                        expected += ['make -j1 V=s']
                self.assertEqual(trace.read_text().splitlines(), expected)
                reported = run('Cache statistics')
                self.assertEqual(reported.returncode, stats)
                if not bootstrap:
                    expected += ['ccache --cleanup cap=2G', 'ccache --show-stats cap=2G']
                self.assertEqual(trace.read_text().splitlines(), expected)


if __name__ == '__main__':
    unittest.main()
