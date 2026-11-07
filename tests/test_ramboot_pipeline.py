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
        (source / 'scripts').mkdir()
        script = source / 'scripts/getver.sh'; script.write_text('#!/bin/sh\necho r43172-4765b65762\n'); script.chmod(0o755)
        git(source, 'add', '.'); git(source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'source fixture, no firmware')
        feed = source / 'feeds/luci'; feed.mkdir(parents=True)
        git(feed, 'init', '-q'); (feed / 'tracked').write_text('official feed object')
        git(feed, 'add', '.'); git(feed, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'feed fixture')
        (source / '.config').write_text((ROOT / 'user/ramboot/config.diff').read_text())
        return source, git

    def test_record_requires_pristine_official_sources_and_minimal_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source, _ = self.fixture(root)
            record = root / 'record.json'
            result = helper('check_ramboot').verify(source, source, record)
            self.assertTrue(result['pristine'])
            self.assertEqual(json.loads(record.read_text()), result)
            self.assertEqual(result['revision'], 'r43172-4765b65762')

    def test_dirty_source_feed_project_overlay_and_lost_language_rejected(self):
        for fault in ('dirty-source', 'dirty-feed', 'files', 'external', 'lost-language', 'r0'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source, _ = self.fixture(root)
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
                        with self.assertRaises(ValueError): helper('check_ramboot').verify(source, source, root / 'record.json')
                    continue
                with self.assertRaises(ValueError): helper('check_ramboot').verify(source, source, root / 'record.json')
