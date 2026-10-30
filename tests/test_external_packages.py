"""Real signed Aurora snapshots/native offline APK tests; no compilation.

Integration inputs are reusable, external fixtures: MX_APK_SOURCE_FIXTURE holds
three exact official assembly files; MX_APK_RUNTIME_FIXTURE contains a native
apk-wrapper executable, eamonxg-mirror and keys/eamonxg.pem; MX_APK_ROOT_FIXTURE
is an isolated real installed APK root (an extracted official image suffices).
Missing integration inputs skip explicitly, never substitute a fake verifier.
Synthetic root metadata below tests only verify_root failure handling, not APK
trust, source package compilation, sing-box execution or target runtime.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGES = ('luci-app-homeproxy', 'luci-i18n-homeproxy-zh-cn', 'sing-box')
RUNTIME_FILES = ('etc/config/homeproxy', 'usr/share/luci/menu.d/luci-app-homeproxy.json',
                 'usr/lib/lua/luci/i18n/homeproxy.zh-cn.lmo')


def helper():
    spec = importlib.util.spec_from_file_location('external_packages', ROOT / 'scripts/external_packages.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(test, name):
    value = os.environ.get(name)
    if not value:
        test.skipTest('set ' + name + ' to an isolated real fixture; no verification substitute')
    assert value is not None
    path = Path(value)
    test.assertTrue(path.is_dir(), str(path))
    return path


def initialize(root):
    (root / 'include').mkdir()
    (root / 'include/version.mk').write_text('VERSION_NUMBER:=25.12.2\n')
    (root / '.config').write_text('CONFIG_USE_APK=y\nCONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n')


def local_repositories(module, directory):
    return {tag: dict(repo, url=(directory / (tag + '-mirror')).as_uri(),
                      key=(directory / 'keys' / (tag + '.pem')).as_uri())
            for tag, repo in module.REPOSITORIES.items()}


class ExternalPackageTests(unittest.TestCase):
    def test_real_assembly_hooks_cover_common_and_device_rootfs(self):
        source = fixture(self, 'MX_APK_SOURCE_FIXTURE')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('package/Makefile', 'include/rootfs.mk', 'include/image.mk'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, path)
            helper().prepare(root)
            common = (root / 'package/Makefile').read_text()
            self.assertLess(common.index('external_packages.py snapshot'), common.index('$(call apk,$(TARGET_DIR)) add'))
            self.assertLess(common.index('$(MX_EXTERNAL_PACKAGES)'), common.index('$(CP) $(TARGET_DIR) $(TARGET_DIR_ORIG)'))
            shared = (root / 'include/rootfs.mk').read_text()
            self.assertIn('$(MX_EXTERNAL_REPOSITORIES)', shared)
            self.assertIn('--no-network', shared)
            self.assertIn('external_packages.py verify-root $(1)', shared)
            self.assertIn('include $(TOPDIR)/.external-packages.mk', shared)
            devices = (root / 'include/image.mk').read_text()
            self.assertIn('$(call apk,$(mkfs_cur_target_dir))', devices)
            self.assertIn('$(call prepare_rootfs,$(mkfs_cur_target_dir)', devices)
            self.assertEqual(devices, (source / 'include/image.mk').read_text())
            feeds = root / 'files/etc/apk/repositories.d/customfeeds.list'
            self.assertNotIn('file://', feeds.read_text())
            first = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            helper().prepare(root)
            self.assertEqual(first, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_signed_snapshot_preserves_official_bytes_and_rejects_tampering(self):
        runtime = fixture(self, 'MX_APK_RUNTIME_FIXTURE')
        module = helper()
        apk = runtime / 'apk-wrapper'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize(root)
            for tag in module.REPOSITORIES:
                shutil.copytree(runtime / (tag + '-mirror'), root / (tag + '-mirror'))
            repositories = local_repositories(module, root)
            for tag in repositories:
                repositories[tag]['key'] = (runtime / 'keys' / (tag + '.pem')).as_uri()
            module.snapshot(root, apk, repositories)
            provenance = root / '.external-packages/provenance.json'
            record = json.loads(provenance.read_text())
            self.assertEqual({p['name'] for p in record['packages']},
                             {p for repo in repositories.values() for p in repo['packages']})
            for tag in repositories:
                self.assertEqual((root / (tag + '-mirror/packages.adb')).read_bytes(),
                                 (root / '.external-packages' / tag / 'packages.adb').read_bytes())
            for row in record['packages']:
                self.assertEqual((root / (row['repository'] + '-mirror') / row['filename']).read_bytes(),
                                 (root / '.external-packages' / row['repository'] / row['filename']).read_bytes())
            tag = 'eamonxg'
            index = root / (tag + '-mirror/packages.adb')
            saved = index.read_bytes()
            index.write_bytes(saved[:-16] + b'x' * 16)
            with self.assertRaises(subprocess.CalledProcessError):
                module.snapshot(root, apk, repositories)
            self.assertFalse(provenance.exists())
            index.write_bytes(saved)
            key = root / 'wrong-key.pem'
            key.write_text('not an upstream public key\n')
            repositories[tag]['key'] = key.as_uri()
            with self.assertRaisesRegex(ValueError, 'signing key changed'):
                module.snapshot(root, apk, repositories)
            self.assertFalse(provenance.exists())
            repositories[tag]['key'] = (runtime / 'keys/eamonxg.pem').as_uri()
            # Restore successful provenance before testing a failed package refresh.
            module.snapshot(root, apk, repositories)
            package = root / (tag + '-mirror') / next(
                row['filename'] for row in record['packages'] if row['name'] == 'luci-theme-aurora')
            saved = package.read_bytes()
            package.write_bytes(saved[:-5] + b'xxxxx')
            with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                module.snapshot(root, apk, repositories)
            self.assertFalse(provenance.exists())

    def test_offline_add_and_per_device_recompute_keep_updatable_world(self):
        runtime = fixture(self, 'MX_APK_RUNTIME_FIXTURE')
        pristine = fixture(self, 'MX_APK_ROOT_FIXTURE')
        module = helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize(root)
            repositories = local_repositories(module, runtime)
            module.snapshot(root, runtime / 'apk-wrapper', repositories)
            image = root / 'rootfs'
            shutil.copytree(pristine, image, symlinks=True,
                            ignore=shutil.ignore_patterns('dev', 'proc', 'sys'))
            command = [str(runtime / 'apk-wrapper'), '--root', str(image), '--keys-dir',
                       str(root / '.external-packages/keys'), '--arch', module.ARCH,
                       '--repositories-file', '/dev/null', '--no-scripts', '--no-logfile', '--no-network']
            for tag in repositories:
                command += ['--repository-config', '@' + tag + ' ' +
                            (root / '.external-packages' / tag / 'packages.adb').as_uri()]
            wanted = [p + '@' + tag for tag, repo in repositories.items() for p in repo['packages']]
            subprocess.run(command + ['add', *wanted], check=True, capture_output=True, text=True)
            shutil.copytree(root / 'files', image, dirs_exist_ok=True)
            (image / 'etc/apk/repositories.d/customfeeds.list').write_text(''.join(
                '@' + tag + ' ' + repo['url'] + '/packages.adb\n' for tag, repo in module.REPOSITORIES.items()))
            record = json.loads((root / '.external-packages/provenance.json').read_text())

            def assert_native_root(target, native):
                query_command = [arg for arg in native if arg != '--no-scripts']
                result = subprocess.run(query_command + ['query', '--fields', 'name,version', '--format', 'json',
                                                  '--installed', '*'], check=True, capture_output=True, text=True)
                rows = json.loads(result.stdout)
                if isinstance(rows, dict):
                    rows = rows['packages']
                installed = {row['name']: row['version'] for row in rows}
                world = (target / 'etc/apk/world').read_text().splitlines()
                for row in record['packages']:
                    self.assertEqual(installed[row['name']], row['version'])
                    self.assertIn(row['name'] + '@' + row['repository'], world)
                # Official base roots need not contain locally compiled proxy
                # packages: exercise the genuine fail-closed boundary, not stubs.
                if all(name in installed for name in SOURCE_PACKAGES):
                    module.verify_root(target, root / '.external-packages/provenance.json')
                else:
                    with self.assertRaisesRegex(ValueError, 'Missing source-built proxy package'):
                        module.verify_root(target, root / '.external-packages/provenance.json')

            assert_native_root(image, command)
            for device in ('v1', 'v2'):
                target = root / ('device-' + device)
                shutil.copytree(image, target, symlinks=True)
                device_command = [str(target) if arg == str(image) else arg for arg in command]
                subprocess.run(device_command + ['del', 'luci-i18n-aurora-config-zh-cn'],
                               check=True, capture_output=True, text=True)
                missing = subprocess.run([arg for arg in device_command if arg != '--no-scripts'] +
                                         ['query', '--format', 'json', '--installed', 'luci-i18n-aurora-config-zh-cn'],
                                         capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(missing.stdout), [])
                subprocess.run(device_command + ['add', 'luci-i18n-aurora-config-zh-cn@eamonxg'],
                               check=True, capture_output=True, text=True)
                assert_native_root(target, device_command)
            # The same native query/upgrade shape used by LuCI's backend.
            query = [arg for arg in command if arg != '--no-scripts']
            for args in (['query', '--fields', 'all', '--format', 'json', '--installed', '--from', 'system', '*'],
                         ['query', '--fields', 'all', '--format', 'json', '--available', '*']):
                result = subprocess.run(query + args, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in module.REPOSITORIES['eamonxg']['packages']:
                    self.assertIn(name, result.stdout)
            subprocess.run(command + ['upgrade', '--simulate', *module.REPOSITORIES['eamonxg']['packages']],
                           check=True, capture_output=True, text=True)
            aurora = json.loads((image / 'usr/share/luci/menu.d/luci-app-aurora.json').read_text())
            self.assertTrue(aurora)
            self.assertTrue(all(not path.startswith('admin/services/') for path in aurora))

    def test_theme_feed_and_source_package_contract(self):
        module = helper()
        self.assertEqual(set(module.REPOSITORIES), {'eamonxg'})
        self.assertEqual(module.REPOSITORIES['eamonxg']['packages'],
                         ['luci-theme-aurora', 'luci-app-aurora-config', 'luci-i18n-aurora-config-zh-cn'])
        self.assertEqual(module.REPOSITORIES['eamonxg']['url'], 'https://openwrt.eamonxg.fun/snapshots/apk')
        recipe = (ROOT / 'user/default/config.diff').read_text()
        for name in SOURCE_PACKAGES:
            self.assertIn('CONFIG_PACKAGE_' + name + '=y', recipe)

    def test_root_verifier_failure_injection_with_transparent_metadata_stubs(self):
        # Deliberately synthetic records/files for unit failure injection ONLY.
        # Real signed-index/package verification is exercised in the test above.
        module = helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = [dict(name=name, version='fixture-version', repository=tag)
                        for tag, repo in module.REPOSITORIES.items() for name in repo['packages']]
            installed = {name: 'fixture-version' for name in SOURCE_PACKAGES}
            installed.update({row['name']: row['version'] for row in packages})
            def write_installed():
                (root / 'lib/apk/db/installed').write_text(''.join(
                    'P:' + name + '\nV:' + version + '\n\n' for name, version in installed.items()))
            def put(name, data=b'unit metadata stub\n'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                return path
            put('lib/apk/db/installed')
            write_installed()
            world = put('etc/apk/world', ''.join(
                row['name'] + '@' + row['repository'] + '\n' for row in packages).encode())
            feeds = put('etc/apk/repositories.d/customfeeds.list', ''.join(
                '@' + tag + ' ' + repo['url'] + '/packages.adb\n'
                for tag, repo in module.REPOSITORIES.items()).encode())
            keys = []
            for tag in module.REPOSITORIES:
                key = put('etc/apk/keys/' + tag + '.pem', b'unit key, not a signature fixture\n')
                keys.append(dict(name=tag, key_sha256=hashlib.sha256(key.read_bytes()).hexdigest()))
            for name in RUNTIME_FILES:
                put(name)
            core = put('usr/bin/sing-box', b'not a compiled core; never executed\n')
            core.chmod(0o755)
            provenance = put('provenance.json', json.dumps(dict(packages=packages, repositories=keys)).encode())
            self.assertEqual(module.verify_root(root, provenance), installed)
            for name in SOURCE_PACKAGES:
                with self.subTest(package=name):
                    version = installed.pop(name)
                    write_installed()
                    with self.assertRaisesRegex(ValueError, 'Missing source-built proxy package'):
                        module.verify_root(root, provenance)
                    installed[name] = version
                    write_installed()
            for name in RUNTIME_FILES:
                path = root / name
                saved = path.read_bytes()
                for state in ('empty', 'missing'):
                    with self.subTest(file=name, state=state):
                        path.write_bytes(b'') if state == 'empty' else path.unlink()
                        with self.assertRaisesRegex(ValueError, 'Missing HomeProxy runtime file'):
                            module.verify_root(root, provenance)
                        path.write_bytes(saved)
            core_bytes = core.read_bytes()
            for state in ('nonexecutable', 'missing'):
                with self.subTest(core=state):
                    core.chmod(0o644) if state == 'nonexecutable' else core.unlink()
                    with self.assertRaisesRegex(ValueError, 'Missing executable sing-box core'):
                        module.verify_root(root, provenance)
                    core.write_bytes(core_bytes)
                    core.chmod(0o755)
            package = packages[0]
            installed[package['name']] = 'wrong-version'
            write_installed()
            with self.assertRaisesRegex(ValueError, 'wrong official APK version'):
                module.verify_root(root, provenance)
            installed[package['name']] = package['version']
            write_installed()
            for path, replacement, error in ((world, b'', 'tagged world'),
                    (feeds, b'file:///build-only/packages.adb\n', 'Build-only repository'),
                    (feeds, b'', 'Missing runtime repository'),
                    (root / 'etc/apk/keys/eamonxg.pem', b'changed key', 'runtime signing key')):
                with self.subTest(error=error):
                    saved = path.read_bytes()
                    path.write_bytes(replacement)
                    with self.assertRaisesRegex(ValueError, error):
                        module.verify_root(root, provenance)
                    path.write_bytes(saved)
            self.assertEqual(module.verify_root(root, provenance), installed)


if __name__ == '__main__':
    unittest.main()
