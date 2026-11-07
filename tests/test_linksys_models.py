"""Four native devices, shared presets and two disjoint image groups; no compilation."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def helper(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LinksysModelsTests(unittest.TestCase):
    def test_four_native_profiles_share_apps_and_keep_device_rootfs(self):
        config = (ROOT / 'user/default/config.diff').read_text()
        for model in ('mx4200v1', 'mx4200v2', 'mx4300', 'homewrk'):
            self.assertIn('CONFIG_TARGET_DEVICE_qualcommax_ipq807x_DEVICE_linksys_' + model + '=y', config)
        self.assertIn('CONFIG_TARGET_PER_DEVICE_ROOTFS=y', config)
        self.assertIn('CONFIG_TARGET_ROOTFS_INITRAMFS=n', config)
        self.assertIn('CONFIG_TARGET_ROOTFS_INITRAMFS=y', (ROOT / 'user/ramboot/config.diff').read_text())

    def test_groups_are_disjoint_and_complete(self):
        profile = helper('build_profile').load(ROOT / 'user/default')
        groups = profile['release_groups']
        self.assertEqual(set(groups), {'mx4200', 'mx4300-homewrk'})
        self.assertEqual(groups['mx4200']['profiles'], ['linksys_mx4200v1', 'linksys_mx4200v2'])
        self.assertEqual(groups['mx4300-homewrk']['profiles'], ['linksys_mx4300', 'linksys_homewrk'])
        names = [name for group in groups.values() for name in group['images']]
        self.assertEqual(len(names), 9)
        self.assertEqual(len(set(names)), 9)
        self.assertEqual(set(names), set(profile['images']))
        self.assertIn('immortalwrt-qualcommax-ipq807x-linksys_homewrk-squashfs-factory.ubi', names)
        self.assertIn('immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb', names)

    def test_group_contract_rejects_overlap_omission_and_wrong_profile(self):
        module = helper('build_profile')
        data = module.load(ROOT / 'user/default')
        with tempfile.TemporaryDirectory() as tmp:
            for fault in ('overlap', 'omission', 'wrong-profile', 'duplicate-profile'):
                broken = copy.deepcopy(data)
                group = broken['release_groups']['mx4300-homewrk']
                if fault == 'overlap': group['images'][0] = data['images'][0]
                if fault == 'omission': group['images'].pop()
                if fault == 'wrong-profile': group['profiles'][0] = 'linksys_wrong'
                if fault == 'duplicate-profile': group['profiles'][0] = 'linksys_mx4200v1'
                (Path(tmp) / 'build.json').write_text(json.dumps(broken))
                with self.subTest(fault=fault), self.assertRaises(ValueError): module.load(tmp)

    def fixture(self, root):
        profile = helper('build_profile').load(ROOT / 'user/default')
        targets = root / 'targets'
        directory = targets / profile['target']
        directory.mkdir(parents=True)
        profiles = {}
        for group in profile['release_groups'].values():
            for board in group['profiles']:
                images = []
                for name in group['images']:
                    if '-' + board + '-' not in name:
                        continue
                    (directory / name).write_bytes(b'fixture-not-firmware')
                    initramfs = '-initramfs-' in name
                    images.append(dict(name=name, type='kernel' if initramfs else
                                       'factory' if 'factory' in name else 'sysupgrade',
                                       filesystem='initramfs' if initramfs else 'squashfs', size=20))
                if board != 'linksys_homewrk':
                    name = f'immortalwrt-qualcommax-ipq807x-{board}-initramfs-uImage.itb'
                    (directory / name).write_bytes(b'fixture-not-firmware')
                    images.append(dict(name=name, type='kernel', filesystem='initramfs', size=20))
                profiles[board] = dict(images=images)
        data = dict(target=profile['target'], version_code='r123-abcdef', profiles=profiles)
        (directory / 'profiles.json').write_text(json.dumps(data))
        return profile, targets, directory, data

    def test_stage_splits_nine_and_ignores_other_native_initramfs_without_hashing(self):
        module = helper('release_images')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, targets, _, _ = self.fixture(root)
            with patch('hashlib.file_digest', side_effect=AssertionError('staging must not hash')):
                module.stage(targets, root / 'firmware')
            for key, group in profile['release_groups'].items():
                self.assertEqual({p.name for p in (root / 'firmware' / key).iterdir()}, set(group['images']))
            self.assertEqual([len(group['images']) for group in profile['release_groups'].values()], [4, 5])

    def test_missing_ubi_wrong_metadata_and_cross_target_reject_before_copy(self):
        module = helper('release_images')
        for fault in ('missing-ubi', 'wrong-size', 'wrong-device', 'extra-bin', 'extra-ubi', 'cross-target',
                      'extra-itb', 'cross-target-itb', 'missing-initramfs', 'empty-initramfs',
                      'symlink-initramfs', 'missing-initramfs-metadata', 'wrong-initramfs-type',
                      'wrong-initramfs-filesystem', 'wrong-initramfs-size'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                profile, targets, directory, data = self.fixture(root)
                image = directory / next(n for n in profile['images'] if n.endswith('.ubi'))
                ram = directory / next(n for n in profile['images'] if '-initramfs-' in n)
                metadata = data['profiles']['linksys_homewrk']['images']
                ram_entry = next(entry for entry in metadata if entry['filesystem'] == 'initramfs')
                if fault == 'missing-initramfs': ram.unlink()
                if fault == 'empty-initramfs': ram.write_bytes(b'')
                if fault == 'symlink-initramfs':
                    ram.rename(directory / 'payload'); ram.symlink_to('payload')
                if fault == 'missing-initramfs-metadata': metadata.remove(ram_entry)
                if fault == 'wrong-initramfs-type': ram_entry['type'] = 'sysupgrade'
                if fault == 'wrong-initramfs-filesystem': ram_entry['filesystem'] = 'squashfs'
                if fault == 'wrong-initramfs-size': ram_entry['size'] += 1
                if fault == 'missing-ubi': image.unlink()
                if fault == 'wrong-size': data['profiles']['linksys_homewrk']['images'][0]['size'] += 1
                if fault == 'wrong-device': data['profiles']['linksys_homewrk']['images'][0]['name'] = profile['images'][0]
                if fault in ('extra-bin', 'extra-ubi'):
                    (directory / ('other-factory.' + fault[6:])).write_bytes(b'x')
                if fault in ('extra-itb', 'cross-target-itb'):
                    parent = directory if fault == 'extra-itb' else targets / 'other/target'
                    parent.mkdir(parents=True, exist_ok=True)
                    (parent / 'other-sysupgrade.itb').write_bytes(b'not firmware')
                if fault == 'cross-target':
                    other = targets / 'other/target'
                    other.mkdir(parents=True)
                    image.rename(other / image.name)
                (directory / 'profiles.json').write_text(json.dumps(data))
                with self.assertRaises(ValueError): module.stage(targets, root / 'firmware')
                self.assertFalse((root / 'firmware').exists())

    def test_build_record_collects_ubi_and_rejects_extras(self):
        module = helper('firmware_images')
        with tempfile.TemporaryDirectory() as tmp:
            profile, targets, directory, _ = self.fixture(Path(tmp))
            images = module.collect(targets, profile)
            self.assertEqual(len(images), 9)
            self.assertTrue(any(row['name'].endswith('.ubi') for row in images))
            self.assertEqual({row['name'] for row in images if '-initramfs-' in row['name']},
                             {'immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb'})
            (directory / 'unexpected-factory.ubi').write_bytes(b'x')
            with self.assertRaises(ValueError): module.collect(targets, profile)
