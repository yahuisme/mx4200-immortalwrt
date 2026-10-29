"""MX4200 kernel stays within native partition; Honk uses same-build detached BTF."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def helper():
    spec = importlib.util.spec_from_file_location('external_packages', ROOT / 'scripts/external_packages.py')
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class DetachedBtfTests(unittest.TestCase):
    def test_recipe_validates_detached_blob_with_real_pahole(self):
        import os
        import shlex
        import shutil
        import subprocess
        pahole = os.environ.get('MX_PAHOLE') or shutil.which('pahole')
        self.assertTrue(pahole, 'set MX_PAHOLE to a verified prebuilt pahole')
        assert pahole
        source = Path(os.environ.get('MX_RAW_BTF', '/sys/kernel/btf/vmlinux'))
        self.assertTrue(source.is_file(), 'provide existing raw BTF, not a compiled test stub')
        recipe = (ROOT / 'scripts/vmlinux-btf/Makefile').read_text()
        command = recipe.split('\ttest -s $(PKG_BUILD_DIR)/vmlinux-btf\n', 1)[1].split('\nendef', 1)[0]
        command = 'set -e\n' + command
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blob = root / 'vmlinux-btf'
            shutil.copyfile(source, blob)
            # An unrelated prebuilt ELF deliberately has no embedded .BTF.
            shutil.copyfile('/usr/bin/true', root / 'shadow_btf.o')
            command = command.replace('$(BTF_PAHOLE)', shlex.quote(pahole)).replace(
                '$(PKG_BUILD_DIR)', shlex.quote(str(root)))
            result = subprocess.run(['sh', '-c', command], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Exercise the real install body without target compilation.
            install = recipe.split('define Package/vmlinux-btf/install\n', 1)[1].split('\nendef', 1)[0]
            install = install.replace('$(INSTALL_DIR)', 'install -d -m0755').replace(
                '$(INSTALL_DATA)', 'install -m0644').replace('$(LN)', 'ln -sf').replace(
                '$(1)', str(root / 'image')).replace('$(PKG_BUILD_DIR)', str(root)).replace(
                '$(KERNEL_RELEASE)', '6.12.103')
            result = subprocess.run(['sh', '-ec', install], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            target = root / 'image/usr/lib/debug/boot/vmlinux'
            self.assertEqual(blob.read_bytes(), target.read_bytes())
            self.assertEqual((target.parent / 'vmlinux-6.12.103').readlink(), Path('vmlinux'))
            # A nonempty corrupt file must not pass simply because test -s does.
            blob.write_bytes(b'not raw BTF')
            result = subprocess.run(['sh', '-c', command], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            # Parsing a valid blob without the required type must also fail.
            data = source.read_bytes()
            self.assertIn(b'sk_buff\0', data)
            blob.write_bytes(data.replace(b'sk_buff\0', b'sk_buxx\0'))
            result = subprocess.run(['sh', '-c', command], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_builder_supplies_working_pahole(self):
        import re
        dockerfile = (ROOT / 'docker/Dockerfile').read_text()
        match = re.search(r'apt-get install .*?(?=&&)', dockerfile, re.S)
        self.assertIsNotNone(match)
        assert match
        self.assertIn('pahole', match.group().split())
        self.assertIn('pahole --version', dockerfile)

    def test_real_kernel_package_output_path(self):
        import struct
        module = helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kernel = root / 'build_dir/target-aarch64_cortex-a53_musl/linux-qualcommax_ipq807x'
            config = kernel / 'linux-6.12.103/.config'
            config.parent.mkdir(parents=True)
            required = ('BPF', 'BPF_SYSCALL', 'BPF_JIT', 'CGROUPS', 'CGROUP_BPF',
                        'NET_NS', 'NET_SCHED', 'NET_CLS_ACT', 'NET_XGRESS', 'NF_TABLES',
                        'NF_TABLES_INET', 'NFT_CT', 'NFT_QUEUE', 'NETFILTER_NETLINK_QUEUE')
            config.write_text(''.join('CONFIG_' + symbol + '=y\n' for symbol in required))
            blob = kernel / 'vmlinux-btf-6.12.103/vmlinux-btf'
            blob.parent.mkdir(parents=True)
            # Header-only boundary fixture, not target compilation evidence.
            blob.write_bytes(struct.pack('<HBB5I', 0xeb9f, 1, 0, 24, 0, 12, 12, 1) + b'\0' * 13)
            module.verify_kernel(root)

    def test_no_embedded_btf_or_foreign_btf_provider(self):
        config = (ROOT / 'user/default/config.diff').read_text()
        self.assertIn('# CONFIG_KERNEL_DEBUG_INFO_BTF is not set', config)
        self.assertNotIn('CONFIG_DWARVES=y', config)
        self.assertIn('CONFIG_PACKAGE_vmlinux-btf=y', config)
        self.assertNotIn('CONFIG_KERNEL_DEBUG_INFO_BTF=y', config)
        module = helper()
        self.assertNotIn('vmlinux-btf-builtin', module.REPOSITORIES['daeuniverse']['packages'])

    def test_same_build_btf_blob_is_required(self):
        module = helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'build_dir/target-aarch64/linux-qualcommax_ipq807x/linux-6.12.103/.config'
            config.parent.mkdir(parents=True)
            required = ('BPF', 'BPF_SYSCALL', 'BPF_JIT', 'CGROUPS', 'CGROUP_BPF',
                        'NET_NS', 'NET_SCHED', 'NET_CLS_ACT', 'NET_XGRESS')
            config.write_text(''.join('CONFIG_' + symbol + '=y\n' for symbol in required) +
                ''.join('CONFIG_' + symbol + '=m\n' for symbol in
                        ('NF_TABLES', 'NF_TABLES_INET', 'NFT_CT', 'NFT_QUEUE', 'NETFILTER_NETLINK_QUEUE')))
            with self.assertRaisesRegex(ValueError, 'BTF'):
                module.verify_kernel(root)
            blob = root / 'package/vmlinux-btf/Makefile'
            blob.parent.mkdir(parents=True)
            blob.write_text('fixture is not BTF output\n')
            with self.assertRaisesRegex(ValueError, 'BTF'):
                module.verify_kernel(root)

    def test_btf_header_rejects_truncation_and_embedded_kernel(self):
        import struct
        module = helper()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'vmlinux'
            for data in (b'', b'not BTF', struct.pack('<HBB5I', 0xeb9f, 1, 0, 24, 0, 12, 12, 1)):
                path.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'BTF'):
                    module.verify_btf(path)
            # Structural parser fixture, not a compiled target blob.
            path.write_bytes(struct.pack('<HBB5I', 0xeb9f, 1, 0, 24, 0, 12, 12, 1) + b'\0' * 13)
            module.verify_btf(path)

    def test_upstream_sources_are_pinned_and_kernel_abi_bound(self):
        recipe = ROOT / 'scripts/vmlinux-btf'
        # Exact provenance is asserted against the reviewed source archive in
        # the integration run; keep the recipe's source ownership explicit here.
        self.assertIn('b41770520cef00652738cdfbbdda44d4de77f3f5', (recipe / 'SOURCES.md').read_text())
        makefile = (recipe / 'Makefile').read_text()
        self.assertIn('EXTRA_DEPENDS:=kernel (=$(LINUX_VERSION)~$(LINUX_VERMAGIC)-r$(LINUX_RELEASE))', makefile)
        self.assertIn('-include $(LINUX_DIR)/include/linux/kconfig.h', makefile)
        self.assertIn('--btf_encode_detached=', makefile)
        self.assertIn('$(PKG_BUILD_DIR)/vmlinux-btf', makefile)
        for name in ('shadow_btf_core.c', 'shadow_btf_modules.c', 'shadow_btf_private.c'):
            self.assertTrue((recipe / 'src' / name).is_file())


if __name__ == '__main__':
    unittest.main()
