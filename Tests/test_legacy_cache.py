"""Execute workflow migration shells; cache extraction is an offline fixture."""
import itertools
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class LegacyCacheTests(unittest.TestCase):
    def test_restore_matrix(self):
        steps = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']
        named = {step.get('name'): step for step in steps}
        self.assertIn('Restore legacy', named, 'split cache has no migration path')
        legacy = named['Restore legacy']
        self.assertEqual(legacy['with']['path'].splitlines(),
                         ['/mnt/build_wrt/dl', '/mnt/build_wrt/.ccache'])
        self.assertEqual(legacy['if'], "steps.cache-selection.outputs.restore-legacy == 'true'")
        protect = named['Protect caches']
        recover = named['Recover caches']
        self.assertIn("steps.protect-current.outcome == 'success'", recover['if'])
        self.assertIn('always()', recover['if'])
        self.assertLess(steps.index(recover), steps.index(named['Snapshot downloads']))
        self.assertLess(steps.index(recover), steps.index(named['Restore toolchain cache']))
        for dl_hit, cc_hit, legacy_hit in itertools.product((False, True), repeat=3):
            with self.subTest(dl=dl_hit, cc=cc_hit, legacy=legacy_hit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name, hit in [('dl', dl_hit), ('.ccache', cc_hit)]:
                    if hit:
                        (root / name).mkdir()
                        (root / name / 'same').write_text('current')
                stamp = root / 'staging_dir/toolchain-test/.built'
                stamp.parent.mkdir(parents=True)
                stamp.write_text('untouched')
                before = stamp.stat().st_mtime_ns
                env = dict(os.environ, LEGACY_MATCHED='legacy', LEGACY_OUTCOME='success', DOWNLOADS_MATCHED='new-key' if dl_hit else '',
                           CCACHE_MATCHED='new-key' if cc_hit else '')
                def run(step):
                    return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c',
                                           step['run'].replace('/mnt/build_wrt', directory)],
                                          env=env, capture_output=True, text=True)
                if not (dl_hit and cc_hit):
                    self.assertEqual(run(protect).returncode, 0)
                    if legacy_hit:
                        for name in ('dl', '.ccache'):
                            (root / name).mkdir(exist_ok=True)
                            (root / name / 'same').write_text('legacy')
                            (root / name / 'legacy-only').write_text('old')
                    self.assertEqual(run(recover).returncode, 0)
                for name, hit in [('dl', dl_hit), ('.ccache', cc_hit)]:
                    if hit or legacy_hit:
                        self.assertEqual((root / name / 'same').read_text(), 'current' if hit else 'legacy')
                        if hit:
                            self.assertFalse((root / name / 'legacy-only').exists())
                    else:
                        self.assertFalse((root / name).exists())
                self.assertEqual(stamp.stat().st_mtime_ns, before)
                self.assertEqual(stamp.read_text(), 'untouched')
                self.assertFalse((root / '.current-cache').exists())


    def test_failed_legacy_extraction_recovers_hit_and_shell_errors_propagate(self):
        steps = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']
        named = {s.get('name'): s for s in steps}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dl').mkdir()
            (root / 'dl/current').write_text('keep')
            env = dict(os.environ, LEGACY_MATCHED='legacy', LEGACY_OUTCOME='success', DOWNLOADS_MATCHED='prefix-hit', CCACHE_MATCHED='')
            def run(name):
                return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', named[name]['run'].replace('/mnt/build_wrt', directory)], env=env, capture_output=True)
            self.assertEqual(run('Protect caches').returncode, 0)
            # A failed extraction may leave partial output; cleanup still runs,
            # but its success never changes the failed action's job status.
            (root / 'dl').mkdir()
            (root / 'dl/partial').write_text('discard')
            self.assertEqual(run('Recover caches').returncode, 0)
            self.assertEqual((root / 'dl/current').read_text(), 'keep')
            self.assertFalse((root / 'dl/partial').exists())
            (root / '.current-cache').mkdir()
            self.assertNotEqual(run('Protect caches').returncode, 0)
        for step in steps:
            if step.get('uses', '').startswith('actions/cache/save'):
                self.assertTrue(step['if'] == 'success()' or step['if'].startswith('success() &&'))
            if step.get('name') in ('Restore legacy', 'Protect caches', 'Recover caches'):
                self.assertNotIn('continue-on-error', step)


if __name__ == '__main__':
    unittest.main()
