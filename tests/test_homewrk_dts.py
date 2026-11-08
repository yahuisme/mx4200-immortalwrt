"""Preserve HomeWRK MAC cells across the QSDK first-child partition fixup."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DTS = Path('target/linux/qualcommax/dts/ipq8174-homewrk.dts')
FIXTURE = ROOT / 'tests/fixtures/homewrk/ipq8174-homewrk.dts'
HELPER = ROOT / 'scripts/homewrk_dts.py'
STUB = '''/ {
    qpic_nand: nand-controller { compatible = "qcom,ipq8074-nand"; };
    blsp1_i2c2: i2c {};
    swport2: port2 {};
    swport3: port3 {};
    swport4: port4 {};
    swport5: port5 {};
    wifi: wifi {};
};
'''


def command(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)


def get(blob, path, prop=None, mode='s'):
    args = ['fdtget', '-t', mode, str(blob), path]
    if prop is not None:
        args.append(prop)
    return command(*args, check=False)


def children(blob, path):
    return command('fdtget', '-l', str(blob), path).stdout.splitlines()


def fixup(blob):
    # QSDK fdt_del_partitions recurses through the first child lacking label,
    # then deletes ALL siblings once the first labelled partition is reached.
    controller = '/nand-controller'
    parent = controller
    while children(blob, parent):
        first = parent + '/' + children(blob, parent)[0]
        if get(blob, first, 'label').returncode == 0:
            for child in children(blob, parent):
                command('fdtput', '-r', str(blob), parent + '/' + child)
            break
        parent = first
    # fdt_node_set_part_info writes plain partitions into first controller child.
    target = controller + '/' + children(blob, controller)[0]
    command('fdtput', '-c', str(blob), target + '/partition@2980000')
    command('fdtput', '-t', 's', str(blob), target + '/partition@2980000', 'label', 'devinfo')


class HomewrkDtsTests(unittest.TestCase):
    def compile(self, folder, text):
        source = folder / 'test.dts'
        text = text.replace('#include "ipq8174-mx4x00.dtsi"', STUB)
        for symbol, value in [('LED_COLOR_ID_RED', '1'), ('LED_COLOR_ID_GREEN', '2'),
                              ('LED_COLOR_ID_BLUE', '3'), ('LED_FUNCTION_STATUS', '"status"')]:
            text = text.replace(symbol, value)
        source.write_text(text)
        blob = folder / 'test.dtb'
        command('dtc', '-I', 'dts', '-O', 'dtb', '-o', str(blob), str(source))
        return blob

    def test_production_customization_runs_guard(self):
        custom = (ROOT / 'user/default/custom.sh').read_text()
        self.assertIn('python3 /cache-scripts/homewrk_dts.py "$DK_OPENWRT"', custom)

    def test_layout_drift_fails_without_writes(self):
        for old, new in [('&qpic_nand {', '&different_nand {'),
                         ('qcom,smem-part', 'fixed-partitions'),
                         ('\n\tnand@0 {', '\n\tnand@1 {')]:
            with self.subTest(change=new), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / DTS
                path.parent.mkdir(parents=True)
                original = FIXTURE.read_text().replace(old, new)
                path.write_text(original)
                result = command('python3', str(HELPER), tmp, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_text(), original)

    def test_guarded_layout_drift_fails_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / DTS
            path.parent.mkdir(parents=True)
            path.write_text(FIXTURE.read_text())
            command('python3', str(HELPER), tmp)
            changed = path.read_text().replace('qcom,smem-part', 'fixed-partitions')
            path.write_text(changed)
            result = command('python3', str(HELPER), tmp, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), changed)

    def test_mac_reference_survives_bootloader_fixup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / DTS
            path.parent.mkdir(parents=True)
            original = FIXTURE.read_text()
            path.write_text(original)
            sibling = path.with_name('ipq8174-mx4300.dts')
            sibling.write_text('unchanged sibling device\n')
            cell = '/nand-controller/nand@0/partitions/partition-devinfo/nvmem-layout/mac_address'
            blob = self.compile(root, original)
            phandle = get(blob, cell, 'phandle', 'x').stdout
            self.assertTrue(phandle.strip())
            fixup(blob)
            self.assertNotEqual(get(blob, cell, 'phandle', 'x').returncode, 0,
                                'Unfixed fixture must reproduce the missing MAC cell')
            result = command('python3', str(HELPER), str(root), check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            modified = path.read_text()
            self.assertEqual(sibling.read_text(), 'unchanged sibling device\n')
            guard = modified.split('&qpic_nand {\n\tstatus = "okay";\n', 1)[1]
            guard = guard.split('\n\tnand@0 {', 1)[0]
            self.assertTrue(guard)
            self.assertEqual(modified.replace(guard, '', 1), original)
            blob = self.compile(root, modified)
            fixup(blob)
            self.assertEqual(get(blob, cell, 'phandle', 'x').returncode, 0)
            self.assertEqual(get(blob, '/nand-controller/partitions', 'status').stdout.strip(), 'disabled')
            self.assertEqual(get(blob, '/nand-controller/nand@0/partitions', 'compatible').stdout.strip(),
                             'qcom,smem-part')
            reference = get(blob, cell, 'phandle', 'x').stdout.strip()
            for port, increment in [('port2', '0'), ('port3', '1'), ('port4', '1'), ('port5', '1')]:
                self.assertEqual(get(blob, '/' + port, 'nvmem-cells', 'x').stdout.split(),
                                 [reference, increment])
            # Native mtd_check_of_node matches partition-devinfo by its label.
            self.assertEqual(get(blob, '/nand-controller/nand@0/partitions/partition-devinfo',
                                 'label').stdout.strip(), 'devinfo')
            result = command('python3', str(HELPER), str(root), check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_text(), modified)


if __name__ == '__main__':
    unittest.main()
