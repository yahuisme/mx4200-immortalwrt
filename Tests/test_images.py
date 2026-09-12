"""Real artifact regression: set MX4200_IMAGE_ASSETS and put fwtool on PATH."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('verify_images', Path(__file__).resolve().parents[1] / 'Scripts/Verify.py')
assert spec is not None and spec.loader is not None
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


@unittest.skipUnless(os.environ.get('MX4200_IMAGE_ASSETS'), 'MX4200_IMAGE_ASSETS not set (real firmware required)')
class RealImages(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tree = Path(self.temp.name)
        self.source = self.tree / 'bin/targets/qualcommax/ipq807x'
        self.source.mkdir(parents=True)
        assets = list(Path(os.environ['MX4200_IMAGE_ASSETS']).glob('*.bin'))
        self.assertEqual(len(assets), 4)
        for path in assets:
            shutil.copyfile(path, self.source / path.name)

    def image(self, kind, version=1):
        return next(self.source.glob(f'*-linksys_mx4200v{version}-squashfs-{kind}.bin'))

    def rejects(self, reason='.'):
        with self.assertRaisesRegex(ValueError, reason):
            verify.images(self.tree)
        self.assertFalse((self.tree / 'upload').exists())

    def rewrite_sysupgrade(self, change_metadata=None, omit=None):
        path = self.image('sysupgrade')
        fwtool = verify.tool(self.tree, 'fwtool')
        metadata = json.loads(subprocess.check_output([fwtool, '-i', '-', str(path)]))
        if change_metadata:
            change_metadata(metadata)
        subprocess.run([fwtool, '-i', '/dev/null', '-t', str(path)], check=True)
        if omit:
            replacement = self.tree / 'replacement.tar'
            with tarfile.open(path) as source, tarfile.open(replacement, 'w') as dest:
                for member in source:
                    if not member.name.endswith('/' + omit):
                        dest.addfile(member, source.extractfile(member) if member.isfile() else None)
            shutil.copyfile(replacement, path)
        info = self.tree / 'metadata.json'
        info.write_text(json.dumps(metadata))
        subprocess.run([fwtool, '-I', str(info), str(path)], check=True)

    def test_wrong_board_with_valid_crc(self):
        self.rewrite_sysupgrade(lambda m: m['version'].update(board='linksys_mx4300'))
        self.rejects()

    def test_wrong_target_with_valid_crc(self):
        self.rewrite_sysupgrade(lambda m: m['version'].update(target='mediatek/filogic'))
        self.rejects()

    def test_wrong_supported_device_with_valid_crc(self):
        self.rewrite_sysupgrade(lambda m: m.update(supported_devices=['linksys,mx4300']))
        self.rejects()

    def test_missing_tar_member_with_valid_crc(self):
        self.rewrite_sysupgrade(omit='CONTROL')
        self.rejects()

    def test_factory_root_mismatch_with_valid_checksum(self):
        path = self.image('factory')
        data = bytearray(path.read_bytes())
        # Change SquashFS data, not a UBI header; repair the outer checksum.
        data[7000000] ^= 1
        checksum = int(subprocess.check_output(['cksum'], input=data[:-256]).split()[0])
        data[-224:-216] = f'{checksum:08X}'.encode()
        path.write_bytes(data)
        self.rejects('rootfs mismatch')

    def test_real_four_pass(self):
        verify.images(self.tree)
        staged = list((self.tree / 'upload').glob('*.bin'))
        self.assertEqual(len(staged), 4)
        for path in staged:
            self.assertEqual(path.read_bytes(), (self.source / path.name).read_bytes())

    def test_factory_corruption(self):
        path = self.image('factory')
        with path.open('r+b') as image:
            image.seek(7000000)
            value = image.read(1)
            image.seek(-1, 1)
            image.write(bytes([value[0] ^ 1]))
        self.rejects()

    def test_factory_truncated(self):
        path = self.image('factory')
        with path.open('r+b') as image:
            image.truncate(path.stat().st_size - 2048)
        self.rejects()

    def test_factory_wrong_variant(self):
        shutil.copyfile(self.image('factory', 2), self.image('factory', 1))
        self.rejects()

    def test_sysupgrade_wrong_variant(self):
        shutil.copyfile(self.image('sysupgrade', 2), self.image('sysupgrade', 1))
        self.rejects()

    def test_sysupgrade_truncated(self):
        path = self.image('sysupgrade')
        with path.open('r+b') as image:
            image.truncate(path.stat().st_size // 2)
        self.rejects()

    def test_sysupgrade_corruption(self):
        path = self.image('sysupgrade')
        with path.open('r+b') as image:
            image.seek(9000)
            image.write(b'CORRUPTED')
        self.rejects()


if __name__ == '__main__':
    unittest.main()
