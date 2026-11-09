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
    dp2: dp2 {}; dp3: dp3 {}; dp4: dp4 {}; dp5: dp5 {};
    qca8075_1: phy1 {}; qca8075_2: phy2 {}; qca8075_3: phy3 {}; qca8075_4: phy4 {};
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

    def test_stable_fixture_matches_recorded_official_source(self):
        import hashlib
        import json
        import os
        identity = json.loads((FIXTURE.parent / 'stable-source.json').read_text())
        raw = (FIXTURE.parent / 'stable-homewrk.dts').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), identity['sha256'])
        source = os.environ.get('MX_OFFICIAL_SOURCE')
        if source and command('git', '-C', source, 'rev-parse', 'HEAD').stdout.strip() == identity['commit']:
            official = subprocess.check_output(['git', '-C', source, 'show', 'HEAD:' + identity['path']])
            self.assertEqual(raw, official)

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

    def test_stable_source_dts_path_preserves_mac_fix_and_rejects_ambiguity(self):
        from scripts.homewrk_dts import prepare
        stable = Path('target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / stable
            path.parent.mkdir(parents=True)
            path.write_text(FIXTURE.read_text())
            prepare(root)
            self.assertIn('status = "disabled";', path.read_text())
            patched = path.read_text()
            prepare(root)
            self.assertEqual(path.read_text(), patched)
            other = root / DTS
            other.parent.mkdir(parents=True)
            other.write_text(FIXTURE.read_text())
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                prepare(root)
            self.assertEqual(path.read_text(), patched)
            self.assertEqual(other.read_text(), FIXTURE.read_text())

    def test_real_stable_layout_gains_factory_mac_and_survives_fixup(self):
        from scripts.homewrk_dts import prepare
        stable = Path('target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts')
        original = (FIXTURE.parent / 'stable-homewrk.dts').read_text()
        for fault in ('', 'partition', 'port'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / stable
                path.parent.mkdir(parents=True)
                text = original
                if fault == 'partition':
                    text = text.replace('qcom,smem-part', 'fixed-partitions')
                if fault == 'port':
                    text = text.replace('label = "wan";', 'label = "changed";')
                path.write_text(text)
                if fault:
                    with self.assertRaisesRegex(ValueError, 'review MAC protection'):
                        prepare(root)
                    self.assertEqual(path.read_text(), text)
                    continue
                prepare(root)
                modified = path.read_text()
                blob = self.compile(root, modified)
                fixup(blob)
                cell = '/nand-controller/nand@0/partitions/partition-devinfo/nvmem-layout/mac_address'
                reference = get(blob, cell, 'phandle', 'x').stdout.strip()
                self.assertTrue(reference)
                for port, offset in ((2, '0'), (3, '1'), (4, '1'), (5, '1')):
                    self.assertEqual(get(blob, '/dp' + str(port), 'nvmem-cells', 'x').stdout.split(),
                                     [reference, offset])
                self.assertEqual(get(blob, '/nand-controller/partitions', 'status').stdout.strip(), 'disabled')
                self.assertEqual(children(blob, '/nand-controller')[0], 'partitions')
                self.assertEqual(get(blob, cell, 'compatible').stdout.strip(), 'mac-base')
                self.assertEqual(get(blob, cell, '#nvmem-cell-cells', 'i').stdout.strip(), '1')
                self.assertEqual(get(blob, cell.rsplit('/', 1)[0], 'compatible').stdout.strip(),
                                 'ascii-eq-delim-env')
                self.assertEqual(get(blob, cell.rsplit('/', 2)[0], 'label').stdout.strip(), 'devinfo')
                # Cells alone are not sufficient: the disabled first child is
                # what prevents the legacy bootloader from deleting them.
                from scripts.homewrk_dts import GUARD
                unguarded = self.compile(root, modified.replace(GUARD, '', 1))
                fixup(unguarded)
                self.assertNotEqual(get(unguarded, cell, 'phandle', 'x').returncode, 0)
                prepare(root)
                self.assertEqual(path.read_text(), modified)

    def test_existing_mac_mapping_drift_fails_before_any_writes(self):
        from scripts.homewrk_dts import prepare
        for layout in ('stable', 'newer'):
            for fault in ('cell', 'offset', 'consumer', 'cell-name'):
                with self.subTest(layout=layout, fault=fault), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    relative = (Path('target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts')
                                if layout == 'stable' else DTS)
                    path = root / relative
                    path.parent.mkdir(parents=True)
                    path.write_text((FIXTURE.parent / 'stable-homewrk.dts').read_text()
                                    if layout == 'stable' else FIXTURE.read_text())
                    prepare(root)
                    text = path.read_text()
                    if fault == 'cell':
                        text = text.replace('compatible = "mac-base";', 'compatible = "unreviewed";')
                    elif fault == 'offset':
                        text = text.replace('nvmem-cells = <&mac_address 0>;', 'nvmem-cells = <&mac_address 1>;')
                    elif fault == 'consumer':
                        text = text.replace('nvmem-cells = <&mac_address 0>;', '')
                    else:
                        text = text.replace('nvmem-cell-names = "mac-address";', 'nvmem-cell-names = "unreviewed";')
                    path.write_text(text)
                    with self.assertRaisesRegex(ValueError, 'review MAC protection'):
                        prepare(root)
                    self.assertEqual(path.read_text(), text)

    def test_factory_mac_mapping_drift_fails_before_writes(self):
        changes = (
            ('compatible = "mac-base";', 'compatible = "invalid";'),
            ('#nvmem-cell-cells = <1>;', '#nvmem-cell-cells = <0>;'),
            ('compatible = "ascii-eq-delim-env";', 'compatible = "invalid";'),
            ('label = "devinfo";', 'label = "invalid";'),
            ('nvmem-cells = <&mac_address 0>;', 'nvmem-cells = <&mac_address 1>;'),
            ('nvmem-cells = <&mac_address 1>;', 'nvmem-cells = <&mac_address 0>;'),
            ('nvmem-cell-names = "mac-address";', 'nvmem-cell-names = "invalid";'),
            ('label = "lan3";', 'label = "invalid";'),
        )
        from scripts.homewrk_dts import GUARD, prepare
        for layout in ('stable', 'newer'):
            for guarded in (False, True):
                for old, new in changes:
                    with self.subTest(layout=layout, guarded=guarded, change=old), tempfile.TemporaryDirectory() as tmp:
                        relative = (Path('target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts')
                                    if layout == 'stable' else DTS)
                        path = Path(tmp) / relative
                        path.parent.mkdir(parents=True)
                        path.write_text((FIXTURE.parent / 'stable-homewrk.dts').read_text()
                                        if layout == 'stable' else FIXTURE.read_text())
                        prepare(tmp)
                        original = path.read_text()
                        if not guarded:
                            original = original.replace(GUARD, '', 1)
                        self.assertIn(old, original)
                        changed = original.replace(old, new, 1)
                        path.write_text(changed)
                        result = command('python3', str(HELPER), tmp, check=False)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(path.read_text(), changed)

    def test_every_port_mapping_is_revalidated_before_writes(self):
        from scripts.homewrk_dts import prepare
        for layout in ('stable', 'newer'):
            for port, offset in ((2, 0), (3, 1), (4, 1), (5, 1)):
                for fault in ('offset', 'consumer', 'name', 'duplicate'):
                    with self.subTest(layout=layout, port=port, fault=fault), tempfile.TemporaryDirectory() as tmp:
                        relative = (Path('target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8174-homewrk.dts')
                                    if layout == 'stable' else DTS)
                        path = Path(tmp) / relative
                        path.parent.mkdir(parents=True)
                        path.write_text((FIXTURE.parent / 'stable-homewrk.dts').read_text()
                                        if layout == 'stable' else FIXTURE.read_text())
                        prepare(tmp)
                        original = path.read_text()
                        prefix = 'dp' if layout == 'stable' else 'swport'
                        start = original.index(f'&{prefix}{port} {{')
                        end = original.index('};', start) + 2
                        block = original[start:end]
                        consumer = f'nvmem-cells = <&mac_address {offset}>;'
                        if fault == 'offset':
                            block = block.replace(consumer, f'nvmem-cells = <&mac_address {1 - offset}>;')
                        elif fault == 'consumer':
                            block = block.replace(consumer, '')
                        elif fault == 'name':
                            block = block.replace('"mac-address"', '"wrong"')
                        else:
                            block = block.replace(consumer, consumer + '\n\t' + consumer)
                        changed = original[:start] + block + original[end:]
                        path.write_text(changed)
                        with self.assertRaisesRegex(ValueError, 'Ethernet MAC mapping changed'):
                            prepare(tmp)
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
