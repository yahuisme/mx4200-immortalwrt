"""Execute the complete compile shell block with isolated make/ccache stubs."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class CompileStatsTests(unittest.TestCase):
    def test_statistics_on_success_and_failure_preserve_status(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())
        block = next(s['run'] for s in workflow['jobs']['build']['steps']
                     if s['name'] == 'Compile firmware')
        for make_failure, stats_failure in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(make_failure=make_failure, stats_failure=stats_failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'staging_dir/host/bin').mkdir(parents=True)
                bindir = root / 'bin'
                bindir.mkdir()
                log = root / 'calls'
                ccache = root / 'staging_dir/host/bin/ccache'
                ccache.write_text('#!/bin/bash\nprintf "ccache %s\\n" "$*" >> "$CALLS"\nif [ "$1" = -s ]; then exit "$STATS_STATUS"; fi\n')
                ccache.chmod(0o755)
                make = bindir / 'make'
                make.write_text('#!/bin/bash\nprintf "make %s\\n" "$*" >> "$CALLS"\nexit "$MAKE_STATUS"\n')
                make.chmod(0o755)
                env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                           CALLS=str(log), MAKE_STATUS='7' if make_failure else '0',
                           STATS_STATUS='9' if stats_failure else '0')
                result = subprocess.run(['bash', '-e', '-c', block.replace('/mnt/build_wrt', str(root))],
                                        env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 7 if make_failure else 0, result.stderr)
                calls = log.read_text().splitlines()
                self.assertEqual(calls[0], 'ccache -z')
                self.assertEqual(calls[-1], 'ccache -s')
                self.assertEqual(calls.count('ccache -s'), 1)
                self.assertEqual(sum(line.startswith('make ') for line in calls), 2 if make_failure else 1)
