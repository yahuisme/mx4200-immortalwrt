"""Local image staging must validate inputs without hashing disposable output."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_images', ROOT / 'scripts/release_images.py')
assert spec is not None and spec.loader is not None
release_images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_images)


class ImageStageTests(unittest.TestCase):
    def fixture(self, root):
        targets = root / 'targets'
        directory = targets / 'qualcommax/ipq807x'
        directory.mkdir(parents=True)
        for device in ('mx4200v1', 'mx4200v2'):
            for kind in ('factory', 'sysupgrade'):
                name = f'immortalwrt-qualcommax-ipq807x-linksys_{device}-squashfs-{kind}.bin'
                (directory / name).write_bytes(name.encode())
        data: dict = dict(target='qualcommax/ipq807x', version_code='r123-abcdef',
                    profiles={'linksys_mx4200v1': {}, 'linksys_mx4200v2': {}})
        (directory / 'profiles.json').write_text(json.dumps(data))
        return targets, directory, data

    def test_stage_copies_exact_images_without_unused_digest_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            targets, directory, _ = self.fixture(root)
            (directory / 'auxiliary.bin').write_bytes(b'not a release image')
            output = root / 'firmware'
            with patch.object(hashlib, 'file_digest', side_effect=AssertionError('unused staging hash')):
                self.assertIsNone(release_images.stage(targets, output))
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()},
                             {p.name: p.read_bytes() for p in directory.glob('*.bin')
                              if p.name != 'auxiliary.bin'})
            self.assertEqual(len(list(output.iterdir())), 4)

    def test_rejects_invalid_image_sets_across_all_targets_before_copy(self):
        for case in ('missing', 'empty', 'directory', 'symlink', 'wrong-name',
                     'extra-factory', 'extra-sysupgrade', 'extra-other-target', 'wrong-parent'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                targets, directory, _ = self.fixture(root)
                image = next(directory.glob('*factory.bin'))
                if case in ('missing', 'directory', 'symlink'):
                    image.unlink()
                if case == 'empty': image.write_bytes(b'')
                if case == 'directory': image.mkdir()
                if case == 'symlink':
                    (directory / 'payload').write_bytes(b'image')
                    image.symlink_to('payload')
                if case == 'wrong-name': image.rename(directory / 'other-factory.bin')
                if case.startswith('extra-'):
                    parent = targets / 'other/target' if case == 'extra-other-target' else directory
                    parent.mkdir(parents=True, exist_ok=True)
                    kind = 'sysupgrade' if case == 'extra-sysupgrade' else 'factory'
                    (parent / f'other-{kind}.bin').write_bytes(b'image')
                if case == 'wrong-parent':
                    parent = targets / 'other/target'
                    parent.mkdir(parents=True)
                    image.rename(parent / image.name)
                output = root / 'firmware'
                with self.assertRaises(ValueError):
                    release_images.stage(targets, output)
                self.assertFalse(output.exists())

    def test_rejects_invalid_profiles_before_copy(self):
        for case in ('target', 'missing-device', 'extra-device', 'revision', 'malformed'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                targets, directory, data = self.fixture(root)
                if case == 'target': data['target'] = 'airoha/an7581'
                if case == 'missing-device': data['profiles'].pop('linksys_mx4200v2')
                if case == 'extra-device': data['profiles']['other'] = {}
                if case == 'revision': data['version_code'] = 'SNAPSHOT'
                (directory / 'profiles.json').write_text('{' if case == 'malformed' else json.dumps(data))
                output = root / 'firmware'
                with self.assertRaises(ValueError):
                    release_images.stage(targets, output)
                self.assertFalse(output.exists())

    def test_staged_output_still_requires_nonempty_regular_nonsymlink_images(self):
        for case in ('empty', 'directory', 'symlink'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                targets, _, _ = self.fixture(root)
                def bad_copy(source, destination):
                    if case == 'empty': destination.touch()
                    if case == 'directory': destination.mkdir()
                    if case == 'symlink': destination.symlink_to(source)
                with patch.object(release_images.shutil, 'copyfile', side_effect=bad_copy):
                    with self.assertRaises(ValueError):
                        release_images.stage(targets, root / 'firmware')
