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

    def test_cache_rotates_and_keeps_restore_prefix(self):
        workflow = (ROOT / '.github/workflows/MX4200.yml').read_text()
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}', workflow)
        self.assertIn('restore-keys: mx4200-build-${{ runner.os }}-${{ runner.arch }}-', workflow)
        self.assertIn('key: ${{ steps.downloads.outputs.cache-primary-key }}', workflow)


if __name__ == '__main__':
    unittest.main()
