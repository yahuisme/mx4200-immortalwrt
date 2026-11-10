"""HomeWRK reuses MX4300's native BDF package and exact v1 selector."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/homewrk_bdf.py'
DTS = 'target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts'
IMAGE = 'target/linux/qualcommax/image/ipq807x.mk'
NATIVE = ('define Device/linksys_homewrk\n'
          '\tDEVICE_PACKAGES += kmod-leds-pca963x ipq-wifi-linksys_homewrk\n'
          'endef\nTARGET_DEVICES += linksys_homewrk\n\n'
          'define Device/linksys_mx4x00\n'
          '\tDEVICE_PACKAGES += ipq-wifi-linksys_mx4200\nendef\n')


class HomewrkBdfTests(unittest.TestCase):
    def prepare(self, root):
        dts, image = root / DTS, root / IMAGE
        dts.parent.mkdir(parents=True)
        image.parent.mkdir(parents=True)
        dts.write_bytes((ROOT / 'tests/fixtures/homewrk/stable-homewrk.dts').read_bytes())
        image.write_text(NATIVE)
        return dts, image

    def run_helper(self, root):
        return subprocess.run(['python3', str(HELPER), str(root)],
                              text=True, capture_output=True)

    def test_shared_package_and_selector_are_narrow_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dts, image = self.prepare(root)
            original = dts.read_text()
            for _ in range(2):
                run = self.run_helper(root)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(dts.read_text(), original.replace(
                    '"Linksys-HomeWRK"', '"Linksys-MX4200v1"'))
                self.assertEqual(image.read_text(), NATIVE.replace(
                    'ipq-wifi-linksys_homewrk', 'ipq-wifi-linksys_mx4200'))

    def test_drift_and_ambiguity_rejected_before_either_write(self):
        for case in ('selector', 'package', 'duplicate', 'missing-donor', 'extra-selector', 'extra-package'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                dts, image = self.prepare(root)
                if case == 'selector':
                    dts.write_text(dts.read_text().replace('Linksys-HomeWRK', 'Unknown'))
                elif case == 'package':
                    image.write_text(NATIVE.replace('ipq-wifi-linksys_homewrk', 'unknown-package'))
                elif case == 'duplicate':
                    image.write_text(NATIVE + NATIVE)
                elif case == 'missing-donor':
                    image.write_text(NATIVE.replace('ipq-wifi-linksys_mx4200', 'unknown-package'))
                elif case == 'extra-selector':
                    dts.write_text(dts.read_text() + '\nqcom,calibration-variant = "Other";\n')
                else:
                    image.write_text(NATIVE.replace('kmod-leds-pca963x ipq-wifi-linksys_homewrk\n',
                                     'kmod-leds-pca963x ipq-wifi-linksys_homewrk\n'
                                     '\tDEVICE_PACKAGES += ipq-wifi-other\n'))
                before = (dts.read_bytes(), image.read_bytes())
                self.assertNotEqual(self.run_helper(root).returncode, 0)
                self.assertEqual((dts.read_bytes(), image.read_bytes()), before)


if __name__ == '__main__':
    unittest.main()
