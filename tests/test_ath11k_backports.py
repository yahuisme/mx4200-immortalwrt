"""Install all default ath11k backports without accepting an unreviewed chain."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import ath11k_backports as hook


class Ath11kBackports(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.recipe = self.root / 'package/kernel/mac80211'
        self.patches = self.recipe / 'patches/ath11k'
        self.patches.mkdir(parents=True)
        self.makefile = self.recipe / 'Makefile'
        self.original = f'PKG_SOURCE_VERSION:=7.2\nPKG_HASH:={hook.SOURCE_HASH}\nPKG_RELEASE:=15\n'
        self.makefile.write_text(self.original)
        self.native = self.patches / '984-native.patch'
        self.native.write_text('native input\n')
        self.lock = patch.object(hook, 'CHAIN_HASH', hook.chain_hash([self.native]))
        self.lock.start()
        self.addCleanup(self.lock.stop)

    def test_installs_all_four_and_is_repeatable(self):
        self.assertEqual(hook.PAYLOAD, ('990-rxdma-page-frag-24254.patch',
                                      '991-mesh-amsdu-26866.patch',
                                      '992-unique-sta-addr-25520.patch',
                                      '993-ce-rx-kmalloc-24713.patch'))
        for _ in range(2):
            hook.prepare(self.root)
            self.assertEqual(self.makefile.read_text(), self.original.replace(':=15', ':=18'))
            self.assertEqual(self.native.read_text(), 'native input\n')
            self.assertEqual({p.name for p in self.patches.iterdir()}, {self.native.name, *hook.PAYLOAD})
            for name in hook.PAYLOAD:
                self.assertEqual((self.patches / name).read_bytes(), (hook.PATCH_DIR / name).read_bytes())

    def test_old_two_patch_release_is_rejected_without_writes(self):
        for name in hook.PAYLOAD[:2]:
            (self.patches / name).write_bytes((hook.PATCH_DIR / name).read_bytes())
        self.makefile.write_text(self.original.replace(':=15', ':=16'))
        before = {p: p.read_bytes() for p in self.recipe.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'partial backport'):
            hook.prepare(self.root)
        self.assertEqual(before, {p: p.read_bytes() for p in self.recipe.rglob('*') if p.is_file()})

    def test_qualified_recipe_assignments_rejected_before_writes_or_repeat_acceptance(self):
        for field, statement in (
                ('source', 'override PKG_SOURCE_VERSION := 7.3'),
                ('source', 'export PKG_HASH = ' + '0' * 64),
                ('package release', 'unexport PKG_RELEASE += 1')):
            for installed in (False, True):
                with self.subTest(installed=installed, field=field):
                    if installed:
                        hook.prepare(self.root)
                    self.makefile.write_text(self.makefile.read_text() + statement + '\n')
                    try:
                        before = {p: p.read_bytes() for p in (self.makefile, *self.patches.iterdir())}
                        with self.assertRaisesRegex(ValueError, 'unreviewed ath11k ' + field):
                            hook.prepare(self.root)
                        self.assertEqual(before, {p: p.read_bytes() for p in (self.makefile, *self.patches.iterdir())})
                    finally:
                        self.makefile.write_text(self.original)
                        for name in hook.PAYLOAD:
                            (self.patches / name).unlink(missing_ok=True)

    def test_each_partial_payload_and_installed_drift_rejects_without_writes(self):
        # Every proper subset, including old releases with two or three patches.
        from itertools import combinations
        for length in range(1, len(hook.PAYLOAD)):
            for selected in combinations(hook.PAYLOAD, length):
                for release in ('15', '16', '17', '18'):
                    with self.subTest(selected=selected, release=release):
                        self.makefile.write_text(self.original.replace(':=15', ':=' + release))
                        for name in selected:
                            (self.patches / name).write_bytes((hook.PATCH_DIR / name).read_bytes())
                        before = {p: p.read_bytes() for p in self.recipe.rglob('*') if p.is_file()}
                        with self.assertRaisesRegex(ValueError, 'partial backport'):
                            hook.prepare(self.root)
                        self.assertEqual(before, {p: p.read_bytes() for p in self.recipe.rglob('*') if p.is_file()})
                        for name in selected:
                            (self.patches / name).unlink()
        self.makefile.write_text(self.original)
        hook.prepare(self.root)
        for name in hook.PAYLOAD:
            path = self.patches / name
            original = path.read_bytes()
            for kind in ('conflict', 'symlink'):
                with self.subTest(name=name, kind=kind):
                    if kind == 'conflict':
                        path.write_bytes(b'changed payload')
                    else:
                        path.unlink()
                        path.symlink_to(hook.PATCH_DIR / name)
                    with self.assertRaisesRegex(ValueError, 'ath11k'):
                        hook.prepare(self.root)
                    self.assertIn('PKG_RELEASE:=18\n', self.makefile.read_text())
                    self.assertEqual(path.is_symlink(), kind == 'symlink')
                    path.unlink()
                    path.write_bytes(original)

    @unittest.skipUnless(os.environ.get('MX_ATH11K_SOURCE'), 'requires exact selected native mac80211 recipe')
    def test_exact_selected_source_hook_and_repeat(self):
        source = Path(os.environ['MX_ATH11K_SOURCE']) / 'package/kernel/mac80211'
        shutil.rmtree(self.recipe)
        shutil.copytree(source, self.recipe)
        self.lock.stop()  # Exercise the production guard, not the synthetic lock.
        for _ in range(2):
            hook.prepare(self.root)
            self.assertIn('PKG_RELEASE:=18\n', self.makefile.read_text())
            self.assertEqual(len(list(self.patches.glob('*.patch'))), 51)
            for name in hook.PAYLOAD:
                self.assertEqual((self.patches / name).read_bytes(), (hook.PATCH_DIR / name).read_bytes())

    @unittest.skipUnless(os.environ.get('MX_BACKPORTS_SOURCE'), 'requires exact fully patched backports source')
    def test_selected_registration_and_mac80211_unique_address_consumer(self):
        root = Path(os.environ['MX_BACKPORTS_SOURCE'])
        mac = (root / 'drivers/net/wireless/ath/ath11k/mac.c').read_text()
        registration = mac[mac.index('static int __ath11k_mac_register('):]
        registration = registration[:registration.index('\n}\n')]
        self.assertEqual(registration.count('ieee80211_hw_set(ar->hw, NEEDS_UNIQUE_STA_ADDR);'), 1)
        self.assertLess(registration.index('NEEDS_UNIQUE_STA_ADDR'), registration.index('ieee80211_register_hw'))
        header = (root / 'include/net/mac80211.h').read_text()
        self.assertIn('IEEE80211_HW_NEEDS_UNIQUE_STA_ADDR', header)
        sta = (root / 'net/mac80211/sta_info.c').read_text()
        start = sta.index('static int sta_info_insert_check(')
        consumer = sta[start:sta.index('\n}\n', start)]
        self.assertRegex(consumer, r'ieee80211_hw_check\(&sdata->local->hw, NEEDS_UNIQUE_STA_ADDR\)')
        self.assertRegex(consumer, r'ieee80211_find_sta_by_ifaddr\(&sdata->local->hw,\s*sta->addr, NULL\)')
        self.assertIn('return -ENOTUNIQ;', consumer)
        start = sta.index('int sta_info_insert_rcu(')
        insert = sta[start:sta.index('\n}\n', start)]
        self.assertLess(insert.index('sta_info_insert_check(sta)'), insert.index('sta_info_insert_finish(sta)'))
        self.assertRegex(insert, r'if \(err\) \{[\s\S]*return err;')

    @unittest.skipUnless(os.environ.get('MX_BACKPORTS_SOURCE'), 'requires exact fully patched backports source')
    def test_ce_rx_uses_kmalloc_and_one_configured_dma_length(self):
        root = Path(os.environ['MX_BACKPORTS_SOURCE'])
        ce = (root / 'drivers/net/wireless/ath/ath11k/ce.c').read_text()

        def function(name):
            start = ce.index(name + '(')
            return ce[start:ce.index('\n}\n', start)]

        post = function('ath11k_ce_rx_post_pipe')
        done = function('ath11k_ce_recv_process_cb')
        cleanup = function('ath11k_ce_rx_pipe_cleanup')
        self.assertNotIn('dev_alloc_skb(', post)
        self.assertRegex(post, r'__alloc_skb\(pipe->buf_sz \+ NET_SKB_PAD,\s*'
                               r'GFP_ATOMIC,\s*SKB_ALLOC_RX, NUMA_NO_NODE\)')
        self.assertLess(post.index('skb_reserve(skb, NET_SKB_PAD)'), post.index('dma_map_single('))
        self.assertRegex(post, r'dma_map_single\(ab->dev, skb->data,\s*pipe->buf_sz, DMA_FROM_DEVICE\)')
        for fn in (post, done, cleanup):
            self.assertRegex(fn, r'dma_unmap_single\([^;]+,\s*pipe->buf_sz, DMA_FROM_DEVICE\)')
            self.assertNotIn('skb_tailroom', fn)
        self.assertIn('pipe->buf_sz < nbytes || nbytes == 0', done)
        self.assertLess(done.index('pipe->buf_sz < nbytes'), done.index('skb_put(skb, nbytes)'))

    def test_rejects_drift_conflicts_and_partial_install_without_writes(self):
        for case in ('native', 'recipe', 'source', 'hash', 'series', 'payload', 'partial'):
            with self.subTest(case=case):
                extra = self.patches / hook.PAYLOAD[0]
                if case == 'native':
                    self.native.write_text('drift\n')
                elif case == 'recipe':
                    self.makefile.write_text(self.original.replace(':=15', ':=18'))
                elif case == 'source':
                    self.makefile.write_text(self.original.replace(':=7.2', ':=unknown'))
                elif case == 'hash':
                    self.makefile.write_text(self.original.replace(hook.SOURCE_HASH, '0' * 64))
                elif case == 'series':
                    extra = self.patches / 'series'
                    extra.write_text(self.native.name + '\n')
                elif case == 'payload':
                    extra.write_text('foreign patch\n')
                else:
                    extra.write_bytes((hook.PATCH_DIR / extra.name).read_bytes())
                before = {p: p.read_bytes() for p in self.recipe.rglob('*') if p.is_file()}
                with self.assertRaisesRegex(ValueError, 'ath11k'):
                    hook.prepare(self.root)
                self.assertEqual(before, {p: p.read_bytes() for p in self.recipe.rglob('*') if p.is_file()})
                extra.unlink(missing_ok=True)
                self.makefile.write_text(self.original)
                self.native.write_text('native input\n')


if __name__ == '__main__':
    unittest.main()
