"""Regression tests for exclusions and rolling cache keys."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify', ROOT / 'Scripts/Verify.py')
assert spec is not None and spec.loader is not None
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class ContractTests(unittest.TestCase):
    def test_disabled_config_contract(self):
        lines = [line for line in (ROOT / 'Config/MX4200.txt').read_text().splitlines()
                 if line.startswith('CONFIG_')]
        disabled = [line[:-2] for line in lines if line.endswith('=n')]
        self.assertTrue(disabled)
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            for style in ('explicit', 'comment', 'absent'):
                base = [line for line in lines if not line.endswith('=n')]
                if style == 'explicit':
                    base += [name + '=n' for name in disabled]
                elif style == 'comment':
                    base += ['# ' + name + ' is not set' for name in disabled]
                (tree / '.config').write_text('\n'.join(base))
                verify.check_config(tree)
            for name in disabled:
                for state in ('y', 'm'):
                    with self.subTest(name=name, state=state):
                        (tree / '.config').write_text('\n'.join(base + [name + '=' + state]))
                        with self.assertRaisesRegex(ValueError, 'forbidden'):
                            verify.check_config(tree)

    def test_cache_rotates_and_selects_exact_freshest_restore(self):
        import yaml
        workflow = (ROOT / '.github/workflows/MX4200.yml').read_text()
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', workflow)
        steps = {s.get('id'): s for s in yaml.safe_load(workflow)['jobs']['build']['steps']}
        self.assertIn('Scripts/CacheSelection.py', steps['cache-selection']['run'])
        for tier, prefix in [('downloads', 'mx4200-build-'), ('ccache', 'mx4200-ccache-')]:
            self.assertNotIn('restore-keys', steps[tier]['with'])
            self.assertIn('steps.cache-selection.outputs.' + tier + '-key', steps[tier]['with']['key'])
            self.assertTrue(steps['save-' + tier]['with']['key'].startswith(prefix))
            self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', steps['save-' + tier]['with']['key'])


if __name__ == '__main__':
    unittest.main()
