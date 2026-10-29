"""Official APK snapshot and rootfs hooks; no firmware compilation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def helper():
    spec = importlib.util.spec_from_file_location('external_packages', ROOT / 'scripts/external_packages.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExternalPackageTests(unittest.TestCase):
    def test_real_assembly_hooks_cover_common_and_device_rootfs(self):
        source = os.environ.get('MX_APK_SOURCE_FIXTURE')
        self.assertTrue(source, 'set MX_APK_SOURCE_FIXTURE to the pinned upstream assembly fixture')
        assert source
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('package/Makefile', 'include/rootfs.mk', 'include/image.mk'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(source) / name, path)
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
            self.assertEqual(devices, (Path(source) / 'include/image.mk').read_text())
            self.assertNotIn('file://', (root / 'files/etc/apk/repositories.d/customfeeds.list').read_text())
            first = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            helper().prepare(root)
            self.assertEqual(first, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_signed_snapshot_preserves_official_bytes_and_rejects_tampering(self):
        fixture = os.environ.get('MX_APK_RUNTIME_FIXTURE')
        self.assertTrue(fixture, 'set MX_APK_RUNTIME_FIXTURE to the verified prebuilt APK fixture')
        assert fixture
        module = helper()
        fixture = Path(fixture)
        apk = fixture / 'apk-wrapper'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'include').mkdir()
            (root / 'include/version.mk').write_text('VERSION_NUMBER:=25.12.2\n')
            (root / '.config').write_text('CONFIG_USE_APK=y\nCONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n')
            repositories = {}
            for tag, repo in module.REPOSITORIES.items():
                source = root / ('source-' + tag)
                shutil.copytree(fixture / (tag + '-mirror'), source)
                key = fixture / 'keys' / (tag + '.pem')
                repositories[tag] = dict(repo, url=source.as_uri(), key=key.as_uri())
            module.snapshot(root, apk, repositories)
            record = json.loads((root / '.external-packages/provenance.json').read_text())
            self.assertEqual({p['name'] for p in record['packages']},
                             {p for repo in repositories.values() for p in repo['packages']})
            for tag in repositories:
                original = root / ('source-' + tag) / 'packages.adb'
                self.assertEqual(original.read_bytes(), (root / '.external-packages' / tag / 'packages.adb').read_bytes())
            original = b''
            for name, expected in (('index', subprocess.CalledProcessError), ('key', ValueError)):
                tag = 'eamonxg'
                source = root / ('source-' + tag)
                if name == 'index':
                    path = source / 'packages.adb'
                    original = path.read_bytes()
                    path.write_bytes(original[:-16] + b'x' * 16)
                else:
                    path = root / 'wrong-key.pem'
                    path.write_text('not an upstream public key\n')
                    repositories[tag]['key'] = path.as_uri()
                with self.assertRaises(expected):
                    module.snapshot(root, apk, repositories)
                self.assertFalse((root / '.external-packages/provenance.json').exists())
                if name == 'index':
                    path.write_bytes(original)
            repositories['eamonxg']['key'] = (fixture / 'keys/eamonxg.pem').as_uri()
            package = next((root / 'source-nikki').glob('nikki-*.apk'))
            saved = package.read_bytes()
            package.write_bytes(saved[:-5] + b'xxxxx')
            with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                module.snapshot(root, apk, repositories)
            self.assertFalse((root / '.external-packages/provenance.json').exists())

    def test_offline_add_and_per_device_recompute_keep_updatable_world(self):
        fixture = os.environ.get('MX_APK_RUNTIME_FIXTURE')
        self.assertTrue(fixture, 'set MX_APK_RUNTIME_FIXTURE')
        assert fixture
        fixture = Path(fixture)
        module = helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'include').mkdir()
            (root / 'include/version.mk').write_text('VERSION_NUMBER:=25.12.2\n')
            (root / '.config').write_text('CONFIG_USE_APK=y\nCONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n')
            repositories = {tag: dict(repo, url=(fixture / (tag + '-mirror')).as_uri(),
                                     key=(fixture / 'keys' / (tag + '.pem')).as_uri())
                            for tag, repo in module.REPOSITORIES.items()}
            module.snapshot(root, fixture / 'apk-wrapper', repositories)
            image = root / 'rootfs'
            pristine = os.environ.get('MX_NIKKI_ROOT_FIXTURE')
            self.assertTrue(pristine, 'set MX_NIKKI_ROOT_FIXTURE to the isolated APK root fixture')
            assert pristine
            shutil.copytree(pristine, image, symlinks=True,
                            ignore=shutil.ignore_patterns('dev', 'proc', 'sys'))
            command = [str(fixture / 'apk-wrapper'), '--root', str(image), '--keys-dir',
                       str(root / '.external-packages/keys'), '--arch', module.ARCH,
                       '--repositories-file', '/dev/null', '--no-scripts', '--no-logfile', '--no-network']
            for tag in repositories:
                command += ['--repository-config', '@' + tag + ' ' +
                            (root / '.external-packages' / tag / 'packages.adb').as_uri()]
            wanted = [p + '@' + tag for tag, repo in repositories.items() for p in repo['packages']]
            subprocess.run(command + ['add', *wanted], check=True, capture_output=True, text=True)
            shutil.copytree(root / 'files', image, dirs_exist_ok=True)
            put = image / 'etc/apk/repositories.d/customfeeds.list'
            put.write_text(''.join('@' + tag + ' ' + repo['url'] + '/packages.adb\n'
                                   for tag, repo in module.REPOSITORIES.items()))
            module.verify_root(image, root / '.external-packages/provenance.json')
            for device in ('v1', 'v2'):
                target = root / ('device-' + device)
                shutil.copytree(image, target, symlinks=True)
                device_command = [str(target) if arg == str(image) else arg for arg in command]
                subprocess.run(device_command + ['del', 'luci-i18n-nikki-zh-cn'],
                               check=True, capture_output=True, text=True)
                subprocess.run(device_command + ['add', 'luci-i18n-nikki-zh-cn@nikki'],
                               check=True, capture_output=True, text=True)
                module.verify_root(target, root / '.external-packages/provenance.json')
            # These are the exact queries/upgrade shape used by LuCI's backend.
            query = [arg for arg in command if arg != '--no-scripts']
            for args in (['query', '--fields', 'all', '--format', 'json', '--installed', '--from', 'system', '*'],
                         ['query', '--fields', 'all', '--format', 'json', '--available', '*']):
                result = subprocess.run(query + args, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('nikki', result.stdout)
                self.assertIn('mihomo-meta', result.stdout)
                self.assertIn('luci-theme-aurora', result.stdout)
            subprocess.run(command + ['upgrade', '--simulate', 'nikki', 'mihomo-meta', 'luci-theme-aurora'],
                           check=True, capture_output=True, text=True)
            config = (image / 'etc/config/nikki').read_text()
            self.assertRegex(config, r"config config 'config'\n(?:[^\n]*\n)*?\s+option 'enabled' '0'")
            self.assertTrue((image / 'usr/share/luci/menu.d/luci-app-nikki.json').is_file())
            self.assertTrue((image / 'usr/lib/lua/luci/i18n/nikki.zh-cn.lmo').is_file())
            for name in ('sing-box', 'luci-app-homeproxy', 'honk', 'luci-app-honk',
                         'luci-lib-daeuniverse', 'vmlinux-btf', 'mihomo-alpha'):
                with (image / 'etc/apk/world').open('a') as stream:
                    stream.write(name + '\n')
                with self.assertRaisesRegex(ValueError, name):
                    module.verify_root(image, root / '.external-packages/provenance.json')
                world = image / 'etc/apk/world'
                world.write_text('\n'.join(world.read_text().splitlines()[:-1]) + '\n')

    def test_nikki_feed_and_dependency_contract(self):
        module = helper()
        self.assertNotIn('daeuniverse', module.REPOSITORIES)
        self.assertEqual(module.REPOSITORIES['nikki']['packages'],
                         ['mihomo-meta', 'nikki', 'luci-app-nikki', 'luci-i18n-nikki-zh-cn'])
        self.assertIn('/openwrt-25.12/aarch64_cortex-a53/nikki', module.REPOSITORIES['nikki']['url'])
        self.assertFalse((ROOT / 'scripts/vmlinux-btf').exists())
        self.assertFalse((ROOT / 'user/default/files/etc/honk/config.dae').exists())
        recipe = (ROOT / 'user/default/config.diff').read_text()
        self.assertNotIn('CONFIG_KERNEL_CGROUP_BPF=y', recipe)
        self.assertNotIn('CONFIG_PACKAGE_vmlinux-btf=y', recipe)
        fixture = os.environ.get('MX_APK_RUNTIME_FIXTURE')
        self.assertTrue(fixture, 'set MX_APK_RUNTIME_FIXTURE')
        assert fixture
        fixture = Path(fixture)
        index = json.loads(subprocess.check_output(
            [str(fixture / 'apk-wrapper'), 'adbdump', '--format', 'json',
             str(fixture / 'nikki-mirror/packages.adb')], text=True))
        for package in index['packages']:
            if package['name'] in ('nikki', 'mihomo-meta'):
                for dependency in package['depends']:
                    if dependency not in ('libc', 'mihomo'):
                        self.assertIn('CONFIG_PACKAGE_' + dependency + '=y', recipe)

if __name__ == '__main__':
    unittest.main()
