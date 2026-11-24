import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'tests/fixtures/edma'
HOOK = REPO / 'scripts/edma_rx_memory.py'
TARGET = Path('target/linux/qualcommax')
DRIVER = TARGET / 'files/drivers/net/ethernet/qualcomm'
DRIVER_FILES = ('qca_edma.c', 'qca_edma.h')
PATCHES = REPO / 'scripts/edma-patches'


def digest(data):
    return hashlib.sha256(data).hexdigest()


class EdmaBackportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'source'
        self.copy_target('snapshot')
        self.use_driver('snapshot')

    def copy_target(self, variant):
        shutil.copytree(FIXTURE / variant / 'target', self.root / 'target', dirs_exist_ok=True)

    def use_driver(self, variant, files=DRIVER_FILES):
        (self.root / DRIVER).mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copy2(FIXTURE / variant / name, self.root / DRIVER / name)

    def invoke(self, hook=HOOK):
        return subprocess.run([sys.executable, str(hook), str(self.root)],
                              capture_output=True, text=True)

    def tree(self):
        return {p.relative_to(self.root): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def accepted(self, status):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record['status'], status)
        for name in DRIVER_FILES:
            self.assertEqual(record['driver_sha256'][name],
                             digest((self.root / DRIVER / name).read_bytes()))
        return record

    def rejected(self, reason, hook=HOOK):
        before = self.tree()
        result = self.invoke(hook)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(self.tree(), before)

    def test_real_snapshot_apply_then_repeat(self):
        shutil.copy2(REPO / 'user/default/config.diff', self.root / '.config')
        before = self.tree()
        record = self.accepted('applied')
        after = self.tree()
        self.assertEqual(before.keys(), after.keys())
        self.assertEqual({p for p in before if before[p][0] != after[p][0]},
                         {DRIVER / name for name in DRIVER_FILES})
        self.assertEqual([p['commit'] for p in record['patches']], [
            'c4252c61fc05b5411c1587b74d899f475693f7b6',
            '0f512bbbb48ae436154f66123e722d89053390e5',
            '1698cc246e28cf9f68e5ac4131a20b757728fe49',
        ])
        for p in record['patches']:
            self.assertEqual(p['sha256'], digest((PATCHES / p['file']).read_bytes()))
        for name in DRIVER_FILES:
            self.assertEqual(record['input_driver_sha256'][name], digest(before[DRIVER / name][0]))
        # Apriori output hashes from the reviewed zero-fuzz predecessor chain,
        # not generated from the production script during this test.
        self.assertEqual(record['driver_sha256'], {
            'qca_edma.c': '6d9f203e1e7737528963854d091a1ba5fbb34a4ca090613e928cc38e5374e800',
            'qca_edma.h': 'b2840e8da2d29a0df2672711956019ae291251566674b1c847aae2349d92765c',
        })
        self.assertEqual(self.accepted('already-applied')['patches'], record['patches'])
        self.assertEqual(self.tree(), after)

    def test_complete_native_donor_is_absorbed_without_rewrites(self):
        self.use_driver('native')
        self.copy_target('native')
        before = self.tree()
        record = self.accepted('native')
        self.assertEqual(record['patches'], [])
        self.assertEqual(record['native_reference'], '1698cc246e28cf9f68e5ac4131a20b757728fe49')
        self.assertEqual(self.tree(), before)

    def test_complete_pr_head_is_also_absorbed(self):
        self.use_driver('native-head')
        self.copy_target('native')
        before = self.tree()
        record = self.accepted('native')
        self.assertEqual(record['patches'], [])
        self.assertEqual(record['native_reference'], '71d7a7dbd47d5e0eae1376df78a4a2f3b210b456')
        self.assertEqual(self.tree(), before)

    def test_mixed_driver_is_rejected(self):
        self.use_driver('native', ('qca_edma.h',))
        self.rejected('unreviewed EDMA driver pair')

    def test_baseline_drift_outside_patch_context_is_rejected(self):
        path = self.root / DRIVER / 'qca_edma.c'
        path.write_bytes(path.read_bytes() + b'\n/* unknown drift */\n')
        self.rejected('unreviewed EDMA driver pair')

    def test_native_without_split_run_drop_is_not_absorbed(self):
        self.use_driver('native')
        self.copy_target('native')
        path = self.root / DRIVER / 'qca_edma.c'
        source = path.read_bytes()
        guard = b'if (unlikely(q->rx_more || (desc_status & EDMA_RXDESC_MORE))) {'
        self.assertEqual(source.count(guard), 1)
        path.write_bytes(source.replace(guard, b'if (false) {'))
        self.rejected('unreviewed EDMA driver pair')

    def test_wrong_target_page_size_is_rejected(self):
        path = self.root / TARGET / 'config-6.18'
        source = path.read_bytes()
        self.assertEqual(source.count(b'CONFIG_ARM64_4K_PAGES=y\n'), 1)
        path.write_bytes(source.replace(b'CONFIG_ARM64_4K_PAGES=y\n', b'CONFIG_ARM64_64K_PAGES=y\n'))
        self.rejected('4 KiB pages')

    def test_changed_skb_fragment_config_is_rejected(self):
        (self.root / '.config').write_text('CONFIG_KERNEL_MAX_SKB_FRAGS=45\n')
        self.rejected('unreviewed skb_shared_info layout')

    def test_disabled_driver_is_rejected_even_on_native_path(self):
        self.use_driver('native')
        self.copy_target('native')
        path = self.root / TARGET / 'ipq807x/config-default'
        source = path.read_bytes()
        self.assertEqual(source.count(b'CONFIG_QCOM_EDMA=y\n'), 1)
        path.write_bytes(source.replace(b'CONFIG_QCOM_EDMA=y\n', b'# CONFIG_QCOM_EDMA is not set\n'))
        self.rejected('CONFIG_QCOM_EDMA=y')

    def test_later_overlay_is_rejected(self):
        path = self.root / str(DRIVER).replace('/files/', '/files-6.18/') / 'qca_edma.c'
        path.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE / 'snapshot/qca_edma.c', path)
        self.rejected('competing EDMA overlay')

    def test_later_kernel_patch_is_rejected_on_native_path(self):
        self.use_driver('native')
        self.copy_target('native')
        path = self.root / TARGET / 'patches-6.18/9999-rx-rework.patch'
        path.write_text('--- a/drivers/net/ethernet/qualcomm/qca_edma.c\n'
                        '+++ b/drivers/net/ethernet/qualcomm/qca_edma.c\n'
                        '@@ -1 +1 @@\n-// SPDX-License-Identifier: GPL-2.0\n'
                        '+// SPDX-License-Identifier: GPL-2.0-only\n')
        self.rejected('kernel patch touches EDMA')

    def test_native_driver_without_its_kbuild_predecessors_is_rejected(self):
        self.use_driver('native')
        self.rejected('unreviewed EDMA Kconfig/Makefile patch for native driver')

    def test_corrupt_last_payload_cannot_leave_partial_backport(self):
        hook = self.root.parent / HOOK.name
        shutil.copy2(HOOK, hook)
        patches = self.root.parent / PATCHES.name
        shutil.copytree(PATCHES, patches)
        patch = patches / '03-half-page-rx.patch'
        patch.write_bytes(patch.read_bytes() + b'\n')
        self.rejected('EDMA patch digest mismatch: 03-half-page-rx.patch', hook)

    def test_native_kbuild_predecessors_replay_in_order(self):
        for variant in ('snapshot', 'native'):
            with self.subTest(variant=variant):
                kernel = self.root.parent / f'kernel-{variant}'
                shutil.copytree(FIXTURE / 'kernel', kernel)
                kbuild = FIXTURE / variant / TARGET / 'patches-6.18'
                patches = sorted(kbuild.glob('*.patch'))
                self.assertEqual([p.name[:4] for p in patches], ['0952', '0953'])
                for patch in patches:
                    result = subprocess.run(
                        ['patch', '-f', '-p1', '--fuzz=0', '--no-backup-if-mismatch', '-i', str(patch)],
                        cwd=kernel, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                qualcomm = kernel / 'drivers/net/ethernet/qualcomm'
                self.assertIn('\tselect PAGE_POOL\n', (qualcomm / 'Kconfig').read_text())
                self.assertIn('obj-$(CONFIG_QCOM_EDMA) += qca_edma.o\n',
                              (qualcomm / 'Makefile').read_text())
