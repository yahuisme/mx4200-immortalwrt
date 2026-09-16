import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HomeProxyTests(unittest.TestCase):
    def setUp(self):
        from Scripts import HostpkgCache
        self.module = HostpkgCache
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pkg = self.root / 'package/luci-app-homeproxy'
        self.pkg.mkdir(parents=True)
        fixtures = ROOT / 'Tests/fixtures/hostpkg'
        (self.pkg / 'Makefile').write_bytes((fixtures / 'homeproxy.Makefile').read_bytes())
        (self.root / 'feeds/luci').mkdir(parents=True)
        (self.root / 'feeds/luci/luci.mk').write_bytes((fixtures / 'luci.mk').read_bytes())
        (self.root / 'bootstrap/bin').mkdir(parents=True)
        (self.root / 'bootstrap/bin/go').write_bytes(b'bootstrap')
        for name in ('htdocs/node.js', 'root/etc/config/homeproxy', 'po/en/homeproxy.po'):
            path = self.pkg / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('runtime')

    def key(self, tc='tc-original'):
        return self.module.cache_key(self.root, tc, self.root / 'bootstrap')

    def test_audited_runtime_and_literal_metadata_are_stable(self):
        original = self.key()
        for name in ('htdocs/node.js', 'root/etc/config/homeproxy', 'po/en/homeproxy.po'):
            path = self.pkg / name
            path.write_text('updated runtime')
            updated = path.stat().st_mtime_ns
            self.assertEqual(self.key(), original)
            self.assertEqual(path.stat().st_mtime_ns, updated)
        recipe = self.pkg / 'Makefile'
        recipe.write_text(recipe.read_text().replace('20260915', '20260916').replace('PKG_RELEASE:=6', 'PKG_RELEASE:=7'))
        self.assertEqual(self.key(), original)
        self.assertEqual(recipe.stat().st_mtime_ns, self.module.EPOCH_NS)


    def test_alias_to_normalized_recipe_is_rejected(self):
        (self.root / 'package/other.mk').symlink_to('luci-app-homeproxy/Makefile')
        with self.assertRaises(ValueError):
            self.key()

    def test_unknown_inputs_disable_runtime_and_metadata_exclusion(self):
        recipe = self.pkg / 'Makefile'
        luci = self.root / 'feeds/luci/luci.mk'
        original = self.key()
        mutations = (
            (recipe, recipe.read_bytes() + b'\n# unknown recipe\n'),
            (recipe, recipe.read_bytes().replace(b'+curl', b'+wget')),
            (recipe, recipe.read_bytes().replace(b'PKG_RELEASE:=6', b'PKG_RELEASE:=$(shell echo 6)')),
            (recipe, recipe.read_bytes() + b'PKG_RELEASE:=7\n'),
            (luci, luci.read_bytes() + b'\n# unknown template\n'),
            (self.pkg / 'src/Makefile', b'compile:'),
            (self.pkg / 'patches/fix.patch', b'patch'),
            (self.pkg / 'unknown.mk', b'include input'),
        )
        for path, data in mutations:
            with self.subTest(path=path, data=data[-50:]):
                previous = path.read_bytes() if path.exists() else None
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                changed = self.key()
                self.assertNotEqual(changed, original)
                payload = self.pkg / 'htdocs/node.js'
                payload.write_text('runtime change')
                self.assertNotEqual(self.key(), changed)
                payload.write_text('runtime')
                if previous is None:
                    path.unlink()
                    if path.parent != self.pkg:
                        path.parent.rmdir()
                else:
                    path.write_bytes(previous)
                self.assertEqual(self.key(), original)

    def test_other_packages_bootstrap_and_toolchain_remain_inputs(self):
        original = self.key()
        self.assertNotEqual(self.key('tc-changed'), original)
        for name in ('package/other/htdocs/a.js', 'feeds/packages/dependency/Makefile',
                     'package/luci-app-homeproxy/tests/test.sh',
                     'package/luci-app-homeproxy/LICENSE',
                     'package/luci-app-homeproxy/UPSTREAM-TRACKING.md', 'bootstrap/bin/go'):
            with self.subTest(name=name):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('before')
                before = self.key()
                path.write_text('after')
                self.assertNotEqual(self.key(), before)

    def test_links_into_runtime_and_hidden_payload_links_are_rejected(self):
        for destination in ('luci-app-homeproxy', 'luci-app-homeproxy/htdocs',
                            'luci-app-homeproxy/htdocs/node.js',
                            'luci-app-homeproxy/root/etc/config/homeproxy',
                            'luci-app-homeproxy/po/en/homeproxy.po'):
            with self.subTest(destination=destination):
                link = self.root / 'package/alias'
                link.symlink_to(destination)
                with self.assertRaises(ValueError):
                    self.key()
                link.unlink()
        for destination in ('node.js', '/outside-missing', '../root'):
            with self.subTest(destination=destination):
                link = self.pkg / 'htdocs/alias'
                link.symlink_to(destination)
                with self.assertRaises(ValueError):
                    self.key()
                link.unlink()

    def test_final_config_invalidates_through_unchanged_toolchain_key(self):
        from Scripts import Cache
        import subprocess
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in ('tools/flock/Makefile', 'toolchain/Makefile', 'include/host-build.mk',
                     'scripts/config/Makefile', 'target/linux/qualcommax/Makefile', '.config'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('input\n')
        def key():
            tc = Cache.prepare(self.root, 'refs/heads/main', 'fixed-host')['tc-key']
            return self.key(tc)
        original = key()
        (self.root / '.config').write_text('CONFIG_LUCI_CSSTIDY=y\n')
        self.assertNotEqual(key(), original)

    def test_real_historical_replay(self):
        import os
        import shutil
        audit = os.environ.get('HOMEPROXY_AUDIT')
        if not audit:
            self.skipTest('Set HOMEPROXY_AUDIT to downloaded commit archives; see fixture README')
        keys, full = [], []
        for ref in ('ab5769214950488d55d30910cb1321eaec27ac0e',
                    '6ff620f4df18eed4321be0778dac03f25909f6ad'):
            sources = list((Path(audit) / ref).glob('*/luci-app-homeproxy'))
            self.assertEqual(len(sources), 1)
            shutil.rmtree(self.pkg)
            shutil.copytree(sources[0], self.pkg, symlinks=True)
            keys.append(self.key())
            full.append(self.module.fingerprint(self.root, ('package', 'feeds')))
        self.assertNotEqual(full[0], full[1])
        self.assertEqual(keys[0], keys[1])

    def test_physical_location_only(self):
        import shutil
        moved = self.root / 'feeds/luci/luci-app-homeproxy'
        shutil.move(self.pkg, moved)
        original = self.key()
        (moved / 'htdocs/node.js').write_text('changed')
        self.assertNotEqual(self.key(), original)


class HostpkgTests(unittest.TestCase):
    def test_archive_tier_and_budget(self):
        from Scripts import Cache
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('build_dir/hostpkg', 'staging_dir/hostpkg'):
                (root / name).mkdir(parents=True)
            self.assertEqual(Cache.paths(root, 'hostpkg'), ['build_dir/hostpkg', 'staging_dir/hostpkg'])
            self.assertTrue(Cache.allowed('build_dir/hostpkg/.built', 'hostpkg'))
            self.assertFalse(Cache.allowed('build_dir/host/.built', 'hostpkg'))
            with tempfile.TemporaryDirectory() as archives:
                archive = Path(archives) / 'hostpkg.tar.gz'
                stamp = root / 'build_dir/hostpkg/.built'
                stamp.write_text('real archive fixture')
                before = stamp.stat().st_mtime_ns
                Cache.pack(root, 'hostpkg', archive)
                stamp.unlink()
                Cache.unpack(root, 'hostpkg', archive)
                self.assertEqual(stamp.stat().st_mtime_ns, before)
                self.assertEqual(stamp.read_text(), 'real archive fixture')
            key = Cache.scope('refs/heads/main') + 'hostpkg-abc'
            self.assertTrue(Cache.admission([], 100, key, 'refs/heads/main')['admitted'])
            self.assertFalse(Cache.admission([{'size_in_bytes': Cache.LIMIT, 'key': 'unrelated', 'ref': 'refs/heads/other'}], 100, key, 'refs/heads/main')['admitted'])

    def test_content_inventory_and_exact_metadata_exclusion(self):
        script = ROOT / 'Scripts/HostpkgCache.py'
        self.assertTrue(script.is_file(), 'hostpkg fingerprint helper missing')
        spec = importlib.util.spec_from_file_location('hostpkg', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('package/feeds', 'feeds/packages/nested', 'feeds/packages.tmp/info', 'bootstrap/bin', 'build_dir/hostpkg'):
                (root / name).mkdir(parents=True)
            (root / 'package/feeds/pkg').symlink_to('../../feeds/packages/nested', target_is_directory=True)
            source = root / 'feeds/packages/nested/Makefile'
            source.write_text('recipe')
            (root / 'bootstrap/bin/go').write_bytes(b'bootstrap')
            stamp = root / 'build_dir/hostpkg/.built'
            stamp.touch()
            stamp_ns = stamp.stat().st_mtime_ns
            def key(tc='tc-original'):
                return module.cache_key(root, tc, root / 'bootstrap')
            original = key()
            (root / 'feeds/packages.tmp/info/random-pid').write_text('generated')
            (root / 'feeds/packages.index').write_text('random cookie')
            self.assertEqual(key(), original)
            self.assertEqual(stamp.stat().st_mtime_ns, stamp_ns)
            self.assertEqual(source.stat().st_mtime_ns, module.EPOCH_NS)
            self.assertNotEqual(key('tc-changed'), original)
            source.write_text('changed')
            self.assertNotEqual(key(), original)
            source.write_text('recipe')
            (root / 'feeds/packages/nested/input.tmp').write_text('real source')
            self.assertNotEqual(key(), original)
            (root / 'feeds/packages/nested/input.tmp').unlink()
            (root / 'feeds/orphan.tmp').write_text('real source')
            self.assertNotEqual(key(), original)
            (root / 'feeds/orphan.tmp').unlink()
            (root / 'bootstrap/bin/go').write_bytes(b'changed bootstrap')
            self.assertNotEqual(key(), original)
            (root / 'package/bad').symlink_to('../feeds/packages.tmp/info/random-pid')
            with self.assertRaises(ValueError):
                key()
