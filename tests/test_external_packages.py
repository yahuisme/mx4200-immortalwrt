"""Stable assembly compatibility and real signed Aurora/native offline APK tests.

MX_APK_SOURCE_FIXTURE supplies four untouched official assembly/version files;
without it, use a clearly source-shaped unit fixture (not remote evidence).
MX_APK_RUNTIME_FIXTURE contains a native apk-wrapper executable,
eamonxg-mirror and keys/eamonxg.pem; MX_APK_ROOT_FIXTURE is an isolated real
installed APK root (an extracted official image suffices).
Missing runtime inputs skip explicitly, never substitute a fake verifier.
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
CPU_PACKAGES = ('luci-app-cpufreq', 'luci-i18n-cpufreq-zh-cn')
CPU_FILES = ('www/luci-static/resources/view/cpufreq.js',
             'usr/share/rpcd/acl.d/luci-app-cpufreq.json',
             'usr/share/luci/menu.d/luci-app-cpufreq.json',
             'usr/lib/lua/luci/i18n/cpufreq.zh-cn.lmo')
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
    if not value and name == 'MX_APK_SOURCE_FIXTURE':
        # Source-shaped unit fixture, NOT remote-source evidence. The install
        # stanza is from official v25.12.2 (4fc16f2985a358bd43bb522e43f05395fcbd6ed5).
        # Run with MX_APK_SOURCE_FIXTURE for untouched official assembly files.
        directory = tempfile.TemporaryDirectory()
        test.addCleanup(directory.cleanup)
        path = Path(directory.name)
        shutil.copytree(ROOT / 'tests/fixtures/snapshot-source', path, dirs_exist_ok=True)
        common = (path / 'package/Makefile').read_text()
        start = common.index('# The rootfs is a function')
        end = common.index('$(curdir)/index: FORCE', start)
        stable = '''$(curdir)/install: $(TMP_DIR)/.build $(curdir)/merge $(curdir)/merge-index
\t- find $(STAGING_DIR_ROOT) -type d | $(XARGS) chmod 0755
\trm -rf $(TARGET_DIR) $(TARGET_DIR_ORIG)
\tmkdir -p $(TARGET_DIR)/tmp
ifneq ($(CONFIG_USE_APK),)
\t$(file >$(TMP_DIR)/apk_install_list,\\
\t    $(foreach pkg,$(shell cat $(PACKAGE_INSTALL_FILES) 2>/dev/null),$(pkg)$(call GetABISuffix,$(pkg))))
\t$(call apk,$(TARGET_DIR)) add --no-cache --initdb --no-scripts --arch $(ARCH_PACKAGES) \\
\t\t--repositories-file /dev/null --repository file://$(PACKAGE_DIR_ALL)/packages.adb \\
\t\t$(if $(CONFIG_SIGNED_PACKAGES),,--allow-untrusted) \\
\t\t$$(cat $(TMP_DIR)/apk_install_list) \\
\t\t\t"base-files=$(shell cat $(STAGING_DIR)/base-files.version)" \\
\t\t\t"libc=$(shell cat $(STAGING_DIR)/libc.version)" \\
\t\t\t"kernel=$(shell cat $(STAGING_DIR)/kernel.version)"
\trm -rf $(TARGET_DIR)/run
endif
\t$(CP) $(TARGET_DIR) $(TARGET_DIR_ORIG)
\t$(call prepare_rootfs,$(TARGET_DIR),$(TOPDIR)/files)

'''
        (path / 'package/Makefile').write_text(common[:start] + stable + common[end:])
        (path / 'include/version.mk').write_text(
            'VERSION_NUMBER:=$(call qstrip,$(CONFIG_VERSION_NUMBER))\n'
            'VERSION_NUMBER:=$(if $(VERSION_NUMBER),$(VERSION_NUMBER),25.12.2)\n')
        return path
    if not value:
        test.skipTest('set ' + name + ' to an isolated real fixture; no verification substitute')
    assert value is not None
    path = Path(value)
    test.assertTrue(path.is_dir(), str(path))
    return path


def initialize(root, source):
    shutil.copytree(source, root, dirs_exist_ok=True)
    (root / '.config').write_text('CONFIG_USE_APK=y\nCONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n')
    helper().prepare(root)  # Runtime tests exercise snapshot's post-prepare recheck.


def local_repositories(module, directory):
    return {tag: dict(repo, url=(directory / (tag + '-mirror')).as_uri(),
                      key=(directory / 'keys' / (tag + '.pem')).as_uri())
            for tag, repo in module.REPOSITORIES.items()}


class ExternalPackageTests(unittest.TestCase):
    def copy_source(self, root):
        shutil.copytree(fixture(self, 'MX_APK_SOURCE_FIXTURE'), root, dirs_exist_ok=True)

    def tree(self, root):
        return {str(p.relative_to(root)): ('link', os.readlink(p)) if p.is_symlink()
                else ('file', p.read_bytes()) if p.is_file() else ('directory',)
                for p in root.rglob('*')}

    def test_prepare_rejects_nonstable_or_malformed_version_without_any_writes(self):
        versions = ('SNAPSHOT', '25.12.2-rc1', '25.12.2beta1', 'v25.12.2', '25.12',
                    '25.12.2garbage', 'prefix25.12.2)', '$(unreviewed,25.12.2)')
        assignments = ['VERSION_NUMBER:=' + value + '\n' for value in versions]
        assignments += ['# missing version assignment\n',
                        'VERSION_NUMBER:=25.12.2\nVERSION_NUMBER:=26.01.0\n',
                        'VERSION_NUMBER:=25.12.2\nVERSION_NUMBER+=suffix\n',
                        'VERSION_NUMBER:=$(if $(VERSION_NUMBER),$(VERSION_NUMBER),26.01.0)\n']
        for version in assignments:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.copy_source(root)
                (root / 'include/version.mk').write_text(version)
                (root / '.external-packages.mk').write_text('existing inputs\n')
                before = self.tree(root)
                with self.assertRaisesRegex(ValueError, 'require numeric ImmortalWrt stable'):
                    helper().prepare(root)
                self.assertEqual(before, self.tree(root))

    def test_version_override_is_checked_before_prepare_writes(self):
        configs = ['CONFIG_VERSION_NUMBER=' + value + '\n' for value in
                   ('"26.01.0"', '"SNAPSHOT"', '"25.12.2-rc1"', '25.12.2', '"25.12.3"')]
        configs += ['CONFIG_VERSION_NUMBER=""\nCONFIG_VERSION_NUMBER=""\n']
        for config in configs:
            with self.subTest(config=config), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.copy_source(root)
                (root / 'include/version.mk').write_text('VERSION_NUMBER:=25.12.2\n')
                (root / '.config').write_text(config)
                before = self.tree(root)
                with self.assertRaisesRegex(ValueError, 'without version override'):
                    helper().prepare(root)
                self.assertEqual(before, self.tree(root))

    def test_supported_versions_prepare_idempotently_without_defconfig(self):
        # Numeric future versions are compatibility probes, not claimed releases.
        for number in ('25.12.2', '25.12.10', '26.01.0', '30.12.123'):
            for version in ('VERSION_NUMBER:=' + number + '\n',
                            'VERSION_NUMBER:=$(call qstrip,$(CONFIG_VERSION_NUMBER))\n'
                            'VERSION_NUMBER:=$(if $(VERSION_NUMBER),$(VERSION_NUMBER),' + number + ')\n'):
                for override in ('', 'CONFIG_VERSION_NUMBER=""\n',
                                 'CONFIG_VERSION_NUMBER="' + number + '"\n'):
                    with self.subTest(number=number, version=version, override=override), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        self.copy_source(root)
                        (root / 'include/version.mk').write_text(version)
                        (root / '.config').write_text(override)
                        helper().prepare(root)
                        before = self.tree(root)
                        helper().prepare(root)
                        self.assertEqual(before, self.tree(root))

    def test_pristine_source_boundary_failure_cannot_leave_partial_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.copy_source(root)
            path = root / 'include/rootfs.mk'
            path.write_text(path.read_text().replace('$(call mklibs,$(1))', '$(call unsupported,$(1))'))
            (root / '.external-packages.mk').write_text('preserve existing generated inputs\n')
            before = self.tree(root)
            with self.assertRaisesRegex(ValueError, 'Unsupported upstream assembly boundary'):
                helper().prepare(root)
            self.assertEqual(before, self.tree(root))

    def test_assembly_drift_rejected_by_preflight_prepare_and_snapshot_without_writes(self):
        mutations = (
            ('package/Makefile', '$(curdir)/install:', '$(curdir)/unreviewed-install:'),
            ('package/Makefile', '$$(cat $(TMP_DIR)/apk_install_list)', '$$(cat $(TMP_DIR)/changed_list)'),
            ('include/rootfs.mk', '--keys-dir', '--changed-keys-dir'),
            ('include/rootfs.mk', '$(call mklibs,$(1))', '$(call changed_mklibs,$(1))'),
            ('package/Makefile', '$(curdir)/index: FORCE', 'define rootfs_cache_key\nendef\n$(curdir)/index: FORCE'),
            ('package/Makefile', '"kernel=$(shell cat $(STAGING_DIR)/kernel.version)"', '"kernel=changed"'),
            ('include/image.mk', '$(call apk,$(mkfs_cur_target_dir)) --no-scripts', '$(call changed_apk,$(mkfs_cur_target_dir)) --no-scripts'),
        )
        for name, old, new in mutations:
            for operation in ('preflight', 'prepare', 'snapshot'):
                with self.subTest(name=name, old=old, operation=operation), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    self.copy_source(root)
                    helper().prepare(root)
                    path = root / name
                    path.write_text(path.read_text().replace(old, new))
                    (root / '.config').write_text('CONFIG_USE_APK=y\nCONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n')
                    (root / '.external-packages').mkdir()
                    (root / '.external-packages/provenance.json').write_text('existing evidence\n')
                    (root / 'sentinel-link').symlink_to('include/rootfs.mk')
                    before = self.tree(root)
                    with self.assertRaisesRegex(ValueError, 'Unsupported upstream assembly boundary'):
                        if operation == 'preflight':
                            helper().reviewed_version(root)
                        elif operation == 'prepare':
                            helper().prepare(root)
                        else:
                            helper().snapshot(root, root / 'must-not-execute-apk')
                    self.assertEqual(before, self.tree(root))

    def test_snapshot_rejects_wrong_or_duplicate_package_manager_config_without_writes(self):
        valid = 'CONFIG_USE_APK=y\nCONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n'
        for config in (valid.replace('CONFIG_USE_APK=y', '# CONFIG_USE_APK=y'),
                       valid.replace('CONFIG_USE_APK=y', 'CONFIG_USE_APK=yes'),
                       valid + 'CONFIG_USE_APK=n\n',
                       valid.replace('aarch64_cortex-a53', 'aarch64_generic'),
                       valid + 'CONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n'):
            with self.subTest(config=config), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.copy_source(root)
                (root / '.config').write_text(config)
                (root / '.external-packages').mkdir()
                (root / '.external-packages/provenance.json').write_text('existing evidence\n')
                before = self.tree(root)
                with self.assertRaisesRegex(ValueError, 'require APK and aarch64_cortex-a53'):
                    helper().snapshot(root, root / 'must-not-execute-apk')
                self.assertEqual(before, self.tree(root))

    def test_snapshot_rechecks_changed_version_without_any_writes(self):
        for version, config in (('SNAPSHOT', ''), ('25.12.2-rc1', ''),
                                ('25.12.2', 'CONFIG_VERSION_NUMBER="26.01.0"\n')):
            with self.subTest(version=version, config=config), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.copy_source(root)
                helper().prepare(root)
                (root / 'include/version.mk').write_text('VERSION_NUMBER:=' + version + '\n')
                (root / '.config').write_text('CONFIG_USE_APK=y\nCONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n' + config)
                (root / '.external-packages').mkdir()
                (root / '.external-packages/provenance.json').write_text('existing evidence\n')
                before = self.tree(root)
                with self.assertRaisesRegex(ValueError, 'require numeric ImmortalWrt stable'):
                    helper().snapshot(root, root / 'must-not-execute-apk')
                self.assertEqual(before, self.tree(root))

    def test_real_assembly_hooks_cover_common_and_device_rootfs(self):
        source = fixture(self, 'MX_APK_SOURCE_FIXTURE')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(source, root, dirs_exist_ok=True)
            helper().prepare(root)
            common = (root / 'package/Makefile').read_text()
            self.assertNotIn('rootfs_cache', common)
            self.assertIn('external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk\n\t$(call apk,$(TARGET_DIR)) add', common)
            self.assertIn('$$(cat $(TMP_DIR)/apk_install_list) $(MX_EXTERNAL_PACKAGES) \\\n', common)
            for name in ('base-files', 'libc', 'kernel'):
                self.assertIn('"' + name + '=$(shell cat $(STAGING_DIR)/' + name + '.version)"', common)
            self.assertLess(common.index('$(MX_EXTERNAL_PACKAGES)'), common.index('$(CP) $(TARGET_DIR) $(TARGET_DIR_ORIG)'))
            shared = (root / 'include/rootfs.mk').read_text()
            self.assertIn('--no-network $(MX_EXTERNAL_REPOSITORIES)', shared)
            self.assertIn('external_packages.py verify-root $(1)', shared)
            self.assertIn('include $(TOPDIR)/.external-packages.mk', shared)
            devices = (root / 'include/image.mk').read_text()
            self.assertIn('$(call apk,$(mkfs_cur_target_dir))', devices)
            self.assertIn('$(call prepare_rootfs,$(mkfs_cur_target_dir)', devices)
            self.assertEqual(devices, (source / 'include/image.mk').read_text())
            self.assertNotIn('file://', (root / 'files/etc/apk/repositories.d/customfeeds.list').read_text())
            before = self.tree(root)
            helper().prepare(root)
            self.assertEqual(before, self.tree(root))

    def test_native_stable_recipe_stops_before_add_when_signed_refresh_fails(self):
        """Execute native add lines with a harmless APK boundary, no compilation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.copy_source(root)
            helper().prepare(root)
            text = (root / 'package/Makefile').read_text()
            start = text.index('\tpython3 /cache-scripts/external_packages.py snapshot')
            end = text.index('\n', text.index('"kernel=$(shell cat $(STAGING_DIR)/kernel.version)"', start))
            recipe = text[start:end]
            recipe = recipe.replace('python3 /cache-scripts/external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk',
                                    'test "$(FAIL)" != yes && touch signed-refresh')
            (root / 'apk_install_list').write_text('native-package\n')
            for name in ('base-files', 'libc', 'kernel'):
                (root / (name + '.version')).write_text('native-version\n')
            (root / 'harness.mk').write_text(
                'TOPDIR:=' + str(root) + '\nTMP_DIR:=$(TOPDIR)\nSTAGING_DIR:=$(TOPDIR)\n'
                'TARGET_DIR:=unused-root\nARCH_PACKAGES:=aarch64_cortex-a53\n'
                'PACKAGE_DIR_ALL:=native-repository\nCONFIG_SIGNED_PACKAGES:=y\n'
                'include $(TOPDIR)/.external-packages.mk\n'
                'apk = printf "%s\\n"\n.PHONY: install\ninstall:\n' + recipe + ' >args\n')
            for fail in (False, True):
                for name in ('args', 'signed-refresh'):
                    (root / name).unlink(missing_ok=True)
                result = subprocess.run(['make', '--no-print-directory', '-sf', 'harness.mk', 'install',
                                         'FAIL=' + ('yes' if fail else 'no')], cwd=root, text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, not fail, result.stderr)
                self.assertEqual((root / 'args').exists(), not fail)
                if not fail:
                    args = (root / 'args').read_text().splitlines()
                    self.assertIn('native-package', args)
                    for name in helper().REPOSITORIES['eamonxg']['packages']:
                        self.assertIn(name + '@eamonxg', args)
                    for name in ('base-files', 'libc', 'kernel'):
                        self.assertIn(name + '=native-version', args)
                    self.assertTrue((root / 'signed-refresh').exists())

    def test_signed_snapshot_preserves_official_bytes_and_rejects_tampering(self):
        runtime = fixture(self, 'MX_APK_RUNTIME_FIXTURE')
        module = helper()
        apk = runtime / 'apk-wrapper'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize(root, fixture(self, 'MX_APK_SOURCE_FIXTURE'))
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
            initialize(root, fixture(self, 'MX_APK_SOURCE_FIXTURE'))
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
            for device in ('mx4200v1', 'mx4200v2', 'mx4300', 'homewrk'):
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
            installed = {name: 'fixture-version' for name in SOURCE_PACKAGES + CPU_PACKAGES}
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
            for name in RUNTIME_FILES + CPU_FILES:
                put(name)
            core = put('usr/bin/sing-box', b'not a compiled core; never executed\n')
            core.chmod(0o755)
            provenance = put('provenance.json', json.dumps(dict(packages=packages, repositories=keys)).encode())
            self.assertEqual(module.verify_root(root, provenance), installed)
            for name in CPU_PACKAGES:
                with self.subTest(cpu_package=name):
                    version = installed.pop(name)
                    write_installed()
                    with self.assertRaisesRegex(ValueError, 'Missing CPU performance package'):
                        module.verify_root(root, provenance)
                    installed[name] = version
                    write_installed()
            for name in CPU_FILES:
                path = root / name
                saved = path.read_bytes()
                path.unlink()
                with self.subTest(cpu_payload=name), self.assertRaisesRegex(ValueError, 'Missing CPU performance runtime file'):
                    module.verify_root(root, provenance)
                path.write_bytes(saved)
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
            for state in ('nonexecutable', 'missing', 'empty', 'directory'):
                with self.subTest(core=state):
                    if state == 'nonexecutable':
                        core.chmod(0o644)
                    elif state == 'missing':
                        core.unlink()
                    elif state == 'empty':
                        core.write_bytes(b'')
                    else:
                        core.unlink()
                        core.mkdir()
                    with self.assertRaisesRegex(ValueError, 'Missing executable sing-box core'):
                        module.verify_root(root, provenance)
                    if core.is_dir():
                        core.rmdir()
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
