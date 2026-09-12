import importlib.util
import itertools
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('selection', ROOT / 'Scripts/CacheSelection.py')
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


class SelectionTests(unittest.TestCase):
    def entry(self, tier, date, **changes):
        result = dict(id=1, ref='refs/heads/main', version=selection.VERSIONS[tier],
                      key=('mx4200-ccache-' if tier == 'ccache' else 'mx4200-build-') + 'Linux-X64-' + date,
                      created_at=date, size_in_bytes=1)
        return dict(result, **changes)

    def test_each_tier_uses_freshest_compatible_generation(self):
        for dl, cc, legacy in itertools.product((None, '2026-01-01', '2026-01-03'), repeat=3):
            entries = []
            for tier, date in [('downloads', dl), ('ccache', cc), ('legacy', legacy)]:
                if date:
                    entries.append(self.entry(tier, date))
            entries += [self.entry('legacy', '2099', ref='refs/heads/other'),
                        self.entry('legacy', '2099', version='wrong'),
                        self.entry('legacy', '2099', size_in_bytes=0),
                        self.entry('legacy', '2099', key='mx4200-build-Linux-ARM64-wrong')]
            selected = selection.select(entries, 'refs/heads/main', 'Linux-X64')
            for tier, date in [('downloads', dl), ('ccache', cc)]:
                self.assertEqual(selected['legacy-' + tier], str(bool(legacy and (not date or legacy > date))).lower())

    def test_recovery_replaces_older_tier_without_merging(self):
        steps = {s.get('name'): s for s in yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']}
        for keep_dl, keep_cc, outcome in itertools.product((False, True), (False, True), ('hit', 'miss', 'failure')):
            with self.subTest(dl=keep_dl, cc=keep_cc, outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for tier in ('dl', '.ccache'):
                    (root / tier).mkdir()
                    (root / tier / 'split-only').write_text('split')
                env = dict(os.environ, DOWNLOADS_MATCHED='split' if keep_dl else '',
                           CCACHE_MATCHED='split' if keep_cc else '',
                           LEGACY_MATCHED='legacy' if outcome == 'hit' else '',
                           LEGACY_OUTCOME='failure' if outcome == 'failure' else 'success')
                def run(name):
                    subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', steps[name]['run'].replace('/mnt/build_wrt', tmp)], env=env, check=True)
                run('Protect caches')
                if outcome != 'miss':
                    for tier in ('dl', '.ccache'):
                        (root / tier).mkdir()
                        (root / tier / 'legacy-only').write_text('combined')
                run('Recover caches')
                for tier, keep in [('dl', keep_dl), ('.ccache', keep_cc)]:
                    use_split = keep or outcome != 'hit'
                    self.assertEqual(sorted(p.name for p in (root / tier).iterdir()), ['split-only' if use_split else 'legacy-only'])
                self.assertFalse((root / '.current-cache').exists())


if __name__ == '__main__':
    unittest.main()
