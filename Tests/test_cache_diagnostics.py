"""Input diagnostics must not change the exact cache/output contract."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'cache_diagnostics', Path(__file__).resolve().parents[1] / 'Scripts/Cache.py')
assert spec is not None and spec.loader is not None
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)
REF = 'refs/heads/main'


class CacheDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / 'tree'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in ['tools/flock/src/flock.c', 'toolchain/Makefile',
                     'include/host-build.mk', 'target/linux/qualcommax/Makefile',
                     'scripts/config/Makefile', 'Makefile', 'rules.mk',
                     'Config.in', 'config/Config-build.in', '.config']:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('private-input:' + name + '\n')
        (self.root / '.gitignore').write_text('conf\n*.o\n')
        self.host = b'private-host-package=1\n'
        real_run = cache.run

        def run(*args, **kwargs):
            if args[0] == 'git':
                return real_run(*args, **kwargs)
            return self.host

        self.commands = self.enterContext(patch.object(cache, 'run', side_effect=run))
        self.enterContext(patch.object(cache.platform, 'system', return_value='Linux'))
        self.enterContext(patch.object(cache.platform, 'machine', return_value='fixed-arch'))

    def invoke(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        output = self.base / 'github-output'
        output.write_text('existing=value\n')
        argv = ['Cache.py', '--output', str(output), 'prepare', '--root',
                str(self.root), '--ref', REF, '--host-id', 'private-host-id']
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            cache.main()
        result = json.loads(stdout.getvalue())
        self.assertEqual({'tc-key', 'rolling-prefix', 'source-files'}, set(result))
        expected = 'existing=value\n' + ''.join(
            f'{k}={result[k]}\n' for k in ('tc-key', 'rolling-prefix', 'source-files'))
        self.assertEqual(expected, output.read_text())
        lines = stderr.getvalue().splitlines()
        self.assertEqual(1, len(lines), 'prepare must emit one diagnostic line on stderr')
        self.assertTrue(lines[0].startswith('cache-inputs sha256/16 '), lines)
        groups = dict(field.split('=', 1) for field in lines[0].split()[2:])
        for digest in groups.values():
            self.assertRegex(digest, r'^[0-9a-f]{16}$')
        self.assertNotIn('private-', stderr.getvalue())
        self.assertNotIn(str(self.root), stderr.getvalue())
        self.assertLess(len(lines[0]), 700)
        return result, groups

    def test_prepare_logs_environment_and_final_config_without_changing_outputs(self):
        with patch.object(cache, 'inputs', wraps=cache.inputs) as inventory:
            result, groups = self.invoke()
        self.assertIn('environment', groups)
        self.assertIn('.config', groups)
        self.assertRegex(result['tc-key'], r'^mx4200-pax-v2-[0-9a-f]{16}-tc-[0-9a-f]{64}$')
        inventory.assert_called_once_with(self.root.resolve())
        self.assertEqual(['git', 'gcc', 'g++', 'ld', 'make', 'dpkg-query'],
                         [c.args[0] for c in self.commands.call_args_list])

    def test_diagnostics_preserve_timestamp_and_generated_output_rules(self):
        stamp = self.root / 'build_dir/host/.built'
        stamp.parent.mkdir(parents=True)
        stamp.write_bytes(b'completed')
        before = stamp.stat().st_mtime_ns
        baseline, groups = self.invoke()
        p = self.root / 'tools/flock/src/flock.c'
        os.utime(p, ns=(1700000000123456789, 1700000000123456789))
        generated = self.root / 'scripts/config/conf'
        generated.write_bytes(b'generated executable')
        generated_time = generated.stat().st_mtime_ns
        self.assertEqual((baseline, groups), self.invoke())
        self.assertEqual(cache.EPOCH_NS, p.stat().st_mtime_ns)
        self.assertEqual(before, stamp.stat().st_mtime_ns)
        self.assertEqual(generated_time, generated.stat().st_mtime_ns)
        p.chmod(0o755)
        changed, after = self.invoke()
        self.assertNotEqual(baseline['tc-key'], changed['tc-key'])
        self.assertEqual({'tools'}, {k for k in groups if groups[k] != after[k]})

    def test_input_bytes_are_read_once_and_symlink_target_changes_are_visible(self):
        target = self.root / 'tools/flock/src/flock.c'
        target.write_bytes(b'x' * (1024 * 1024 + 7))
        alias = self.root / 'tools/alias'
        alias.symlink_to('flock/src/flock.c')
        names = cache.inputs(self.root)
        opened = []
        real_open = Path.open

        def open_file(path, *args, **kwargs):
            if args == ('rb',):
                opened.append(str(path.relative_to(self.root)))
            return real_open(path, *args, **kwargs)

        with patch.object(Path, 'open', open_file), \
                patch.object(cache.os, 'utime', wraps=os.utime) as utime:
            baseline, groups = self.invoke()
        self.assertEqual(names, opened)
        self.assertEqual(len(names), utime.call_count)
        target.write_bytes(target.read_bytes()[:-1] + b'y')
        changed, after = self.invoke()
        self.assertNotEqual(baseline['tc-key'], changed['tc-key'])
        self.assertEqual({'tools'}, {k for k in groups if groups[k] != after[k]})

    def test_source_root_digests_isolate_each_input_mutation(self):
        baseline, groups = self.invoke()
        self.assertEqual({'environment', '.config', 'tools', 'toolchain', 'include',
                          'target', 'scripts', 'Makefile', 'rules.mk', 'Config.in', 'config'},
                         set(groups))
        for name in cache.inputs(self.root):
            with self.subTest(name=name):
                p = self.root / name
                original = p.read_bytes()
                p.write_bytes(original + b'changed\n')
                changed, after = self.invoke()
                self.assertEqual({name.split('/')[0]},
                                 {k for k in groups if groups[k] != after[k]})
                self.assertNotEqual(baseline['tc-key'], changed['tc-key'])
                p.write_bytes(original)
        self.host += b'changed-package=2\n'
        changed, after = self.invoke()
        self.assertEqual({'environment'}, {k for k in groups if groups[k] != after[k]})
        self.assertNotEqual(baseline['tc-key'], changed['tc-key'])


if __name__ == '__main__':
    unittest.main()
