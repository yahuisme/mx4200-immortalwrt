"""Standalone RAM metadata/configuration boundaries with private Git objects."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NAME = 'immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb'


def helper(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StageRambootTests(unittest.TestCase):
    def fixture(self, root):
        source, target = root / 'ram', root / 'main'
        source.mkdir(); target.mkdir()
        data = b'private metadata fixture; not firmware'
        (source / NAME).write_bytes(data)
        entry = dict(name=NAME, filesystem='initramfs', type='kernel', size=len(data))
        metadata: dict = dict(target='qualcommax/ipq807x', version_code='r43172-4765b65762',
                        profiles={'linksys_homewrk': {'images': [entry]}})
        (source / 'profiles.json').write_text(json.dumps(metadata))
        main = dict(metadata, profiles={'linksys_homewrk': {'images': [dict(
            name='homewrk-squashfs-sysupgrade.bin', type='sysupgrade', filesystem='squashfs', size=1)]}})
        (target / 'profiles.json').write_text(json.dumps(main))
        return source, target, metadata, main

    def test_only_ram_image_and_one_metadata_entry_are_added(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target, metadata, main = self.fixture(Path(directory))
            helper('stage_ramboot').stage(source, target)
            merged = json.loads((target / 'profiles.json').read_text())
            expected = main['profiles']['linksys_homewrk']['images'] + metadata['profiles']['linksys_homewrk']['images']
            self.assertEqual(merged['profiles']['linksys_homewrk']['images'], expected)
            self.assertEqual((target / NAME).read_bytes(), (source / NAME).read_bytes())
            self.assertEqual({p.name for p in target.iterdir()}, {NAME, 'profiles.json'})

    def test_bad_source_or_preexisting_customized_ram_rejected_before_write(self):
        cases = ('revision', 'target', 'extra-profile', 'type', 'filesystem', 'size',
                 'empty', 'missing', 'symlink', 'duplicate', 'customized-output', 'customized-metadata')
        for fault in cases:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                source, target, metadata, main = self.fixture(Path(directory))
                image = source / NAME
                entry = metadata['profiles']['linksys_homewrk']['images'][0]
                if fault == 'revision': metadata['version_code'] = 'r0-4765b65'
                if fault == 'target': metadata['target'] = 'other/target'
                if fault == 'extra-profile': metadata['profiles']['linksys_mx4300'] = {}
                if fault == 'type': entry['type'] = 'sysupgrade'
                if fault == 'filesystem': entry['filesystem'] = 'squashfs'
                if fault == 'size': entry['size'] += 1
                if fault == 'empty': image.write_bytes(b'')
                if fault == 'missing': image.unlink()
                if fault == 'symlink': image.rename(source / 'payload'); image.symlink_to('payload')
                if fault == 'duplicate': metadata['profiles']['linksys_homewrk']['images'].append(dict(entry))
                if fault == 'customized-output': (target / NAME).write_bytes(b'must not be reused')
                if fault == 'customized-metadata': main['profiles']['linksys_homewrk']['images'].append(dict(entry))
                (source / 'profiles.json').write_text(json.dumps(metadata))
                (target / 'profiles.json').write_text(json.dumps(main))
                before = {p.name: p.read_bytes() for p in target.iterdir()}
                with self.assertRaises(ValueError): helper('stage_ramboot').stage(source, target)
                self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir()})


class RamSourceTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'source'; source.mkdir()
        def git(path, *args):
            return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.DEVNULL, text=True).strip()
        git(source, 'init', '-q', '-b', 'master')
        git(source, 'remote', 'add', 'origin', 'https://github.com/immortalwrt/immortalwrt.git')
        (source / '.gitignore').write_text('.config\nfeeds/\n')
        (source / 'feeds.conf').write_text('src-git luci https://github.com/immortalwrt/luci.git\n')
        (source / 'feeds.conf.default').write_bytes((source / 'feeds.conf').read_bytes())
        (source / 'scripts').mkdir()
        script = source / 'scripts/getver.sh'; script.write_text('#!/bin/sh\necho r43172-4765b65762\n'); script.chmod(0o755)
        git(source, 'add', '.'); git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'source fixture, no firmware')
        feed = source / 'feeds/luci'; feed.mkdir(parents=True)
        git(feed, 'init', '-q'); (feed / 'tracked').write_text('official feed object')
        git(feed, 'remote', 'add', 'origin', 'https://github.com/immortalwrt/luci.git')
        git(feed, 'add', '.'); git(feed, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'feed fixture')
        (source / '.config').write_text((ROOT / 'user/ramboot/config.diff').read_text())
        return source, git

    def baseline(self, source, root):
        """Private native-output fixture, not evidence of a real Kconfig run."""
        module = helper('check_ramboot')
        baseline = root / 'baseline.config'
        baseline.write_text(module.CANONICAL_SEED + '''CONFIG_TARGET_ROOTFS_SQUASHFS=y
CONFIG_BUSYBOX_DEFAULT_PING=y
CONFIG_VERSION_DIST="ImmortalWrt"
CONFIG_GOLANG_BUILD_BOOTSTRAP=y
CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT=""
CONFIG_GOLANG_BUILD_CACHE_DIR=""
''')
        metadata = dict(module.identity(source, source), seed_sha256=module.digest(module.CANONICAL_SEED.encode()),
                        config_sha256=module.digest(baseline.read_bytes()), resolver='make defconfig', schema=1)
        Path(str(baseline) + '.json').write_text(json.dumps(metadata))
        (source / '.config').write_bytes(baseline.read_bytes())
        return baseline

    def test_record_requires_pristine_official_sources_and_minimal_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, _ = self.fixture(root)
            baseline = self.baseline(source, root)
            record = root / 'record.json'
            result = helper('check_ramboot').verify(source, source, record, baseline)
            self.assertTrue(result['pristine'])
            self.assertEqual(json.loads(record.read_text()), result)
            self.assertEqual(result['revision'], 'r43172-4765b65762')

    def test_final_extra_application_cannot_claim_pristine_without_native_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, _ = self.fixture(root)
            with (source / '.config').open('a') as stream:
                stream.write('CONFIG_PACKAGE_luci-app-homeproxy=y\n')
            with self.assertRaisesRegex(ValueError, 'baseline is mandatory'):
                helper('check_ramboot').verify(source, source, root / 'record.json')

    def test_entire_resolved_target_semantics_not_a_known_bad_symbol_blacklist(self):
        mutations = {
            'extra-app': '\nCONFIG_PACKAGE_luci-app-homeproxy=y\n',
            'unknown-future-app': '\nCONFIG_PACKAGE_future-app=m\n',
            'version': 'CONFIG_VERSION_DIST="ProjectRAM"',
            'rootfs': '# CONFIG_TARGET_ROOTFS_SQUASHFS is not set',
            'busybox': '# CONFIG_BUSYBOX_DEFAULT_PING is not set',
            'kernel': '\nCONFIG_KERNEL_DEBUG_INFO=y\n',
            'host-not-exempt': '\nCONFIG_GOLANG_BUILD_CACHE_DIR="/custom"\n',
            'lost-default': '',
        }
        for fault, mutation in mutations.items():
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source, _ = self.fixture(root)
                baseline = self.baseline(source, root)
                text = baseline.read_text()
                if fault in ('version', 'rootfs', 'busybox', 'lost-default', 'host-not-exempt'):
                    old = {'version': 'CONFIG_VERSION_DIST="ImmortalWrt"',
                           'rootfs': 'CONFIG_TARGET_ROOTFS_SQUASHFS=y',
                           'busybox': 'CONFIG_BUSYBOX_DEFAULT_PING=y',
                           'lost-default': 'CONFIG_BUSYBOX_DEFAULT_PING=y',
                           'host-not-exempt': 'CONFIG_GOLANG_BUILD_CACHE_DIR=""'}[fault]
                    text = text.replace(old, mutation.strip())
                else:
                    text += mutation
                (source / '.config').write_text(text)
                with self.assertRaisesRegex(ValueError, 'differs from official resolved baseline'):
                    helper('check_ramboot').verify(source, source, root / 'record.json', baseline)
                self.assertFalse((root / 'record.json').exists())

    def test_semantic_layout_and_disabled_notation_are_not_differences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, _ = self.fixture(root)
            baseline = self.baseline(source, root)
            # Package punctuation, quoted # and escaped quotes occur in real configs.
            additions = 'CONFIG_PACKAGE_luci-base=y\nCONFIG_PACKAGE_libfoo+bar=m\nCONFIG_TEST="hash # and \\\"quote\\\""\n'
            baseline.write_text(baseline.read_text() + additions)
            meta = Path(str(baseline) + '.json')
            proof = json.loads(meta.read_text())
            proof['config_sha256'] = helper('check_ramboot').digest(baseline.read_bytes())
            meta.write_text(json.dumps(proof))
            (source / '.config').write_text('# generated header changed\n' + '\n'.join(reversed(baseline.read_text().splitlines())) +
                                           '\n# CONFIG_DISABLED is not set\nCONFIG_OTHER_DISABLED=n\n')
            result = helper('check_ramboot').verify(source, source, root / 'record.json', baseline)
            self.assertTrue(result['pristine'])

    def test_baseline_is_mandatory_regular_separate_and_identity_bound(self):
        for fault in ('missing', 'symlink', 'same-file', 'hardlink', 'missing-proof',
                      'changed-bytes', 'source', 'feeds', 'seed', 'resolver'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source, _ = self.fixture(root)
                baseline = self.baseline(source, root)
                proof = Path(str(baseline) + '.json')
                if fault == 'missing': baseline.unlink()
                if fault == 'symlink':
                    baseline.rename(root / 'payload'); baseline.symlink_to(root / 'payload')
                if fault == 'same-file': baseline = source / '.config'
                if fault == 'hardlink':
                    baseline.unlink(); baseline.hardlink_to(source / '.config')
                if fault == 'missing-proof': proof.unlink()
                if fault == 'changed-bytes': baseline.write_text(baseline.read_text() + '# changed\n')
                if fault in ('source', 'feeds', 'seed', 'resolver'):
                    data = json.loads(proof.read_text())
                    field = {'source':'source_sha', 'feeds':'feeds', 'seed':'seed_sha256', 'resolver':'resolver'}[fault]
                    data[field] = 'wrong'
                    proof.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    helper('check_ramboot').verify(source, source, root / 'record.json', baseline)
                self.assertFalse((root / 'record.json').exists())

    def test_exact_host_only_controls_accepted_but_wrong_values_are_not(self):
        module = helper('check_ramboot')
        for fault in ('', 'cache-dir', 'bootstrap-dir', 'go-cache', 'target-go-option'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source, _ = self.fixture(root)
                baseline = self.baseline(source, root)
                text = baseline.read_text().replace('CONFIG_GOLANG_BUILD_BOOTSTRAP=y', '# CONFIG_GOLANG_BUILD_BOOTSTRAP is not set')
                text = text.replace('CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT=""', 'CONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT="/usr/lib/go"')
                text += 'CONFIG_CCACHE=y\nCONFIG_CCACHE_DIR="/ghcache"\n'
                if fault == 'cache-dir': text = text.replace('"/ghcache"', '"/arbitrary"')
                if fault == 'bootstrap-dir': text = text.replace('"/usr/lib/go"', '"/arbitrary"')
                if fault == 'go-cache': text = text.replace('CONFIG_GOLANG_BUILD_CACHE_DIR=""', 'CONFIG_GOLANG_BUILD_CACHE_DIR="/custom"')
                if fault == 'target-go-option': text += 'CONFIG_GOLANG_SPECTRE=y\n'
                (source / '.config').write_text(text)
                if fault:
                    with self.assertRaisesRegex(ValueError, 'differs from official resolved baseline'):
                        module.verify(source, source, root / 'record.json', baseline)
                else:
                    result = module.verify(source, source, root / 'record.json', baseline)
                    self.assertEqual(set(result['host_only_differences']), set(module.HOST_VALUES))

    def test_cli_never_silently_verifies_without_baseline(self):
        result = subprocess.run(['python3', str(ROOT / 'scripts/check_ramboot.py'), 'missing', 'missing', 'record'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--configure --baseline', result.stderr)

    def test_dirty_source_feed_project_overlay_and_lost_language_rejected(self):
        for fault in ('dirty-source', 'dirty-feed', 'files', 'external', 'lost-language', 'r0'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source, _ = self.fixture(root)
                baseline = self.baseline(source, root)
                if fault == 'dirty-source': (source / 'feeds.conf').write_text('mutated source')
                if fault == 'dirty-feed': (source / 'feeds/luci/tracked').write_text('custom recipe')
                if fault == 'files': (source / 'files').mkdir()
                if fault == 'external': (source / '.external-packages.mk').touch()
                if fault == 'lost-language': (source / '.config').write_text((source / '.config').read_text().replace('CONFIG_LUCI_LANG_zh_Hans=y', ''))
                if fault == 'r0':
                    # Actual getver regression is exercised separately with full/shallow Git.
                    original = subprocess.check_output
                    with patch('subprocess.check_output', wraps=original) as output:
                        def run(args, **kwargs):
                            if str(args[0]).endswith('getver.sh'): return 'r0-4765b65\n'
                            return original(args, **kwargs)
                        output.side_effect = run
                        with self.assertRaises(ValueError): helper('check_ramboot').verify(source, source, root / 'record.json', baseline)
                    continue
                with self.assertRaises(ValueError): helper('check_ramboot').verify(source, source, root / 'record.json', baseline)
