"""Exercise the source fix and native helper without touching router data."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/ath11k-caldata-helper.sh'


class Ath11kCaldataTests(unittest.TestCase):
    def prepare(self, base):
        path = base / 'package/base-files/files/lib/functions/caldata.sh'
        path.parent.mkdir(parents=True)
        path.write_bytes(FIXTURE.read_bytes())
        return path

    def apply(self, base):
        custom = (ROOT / 'user/default/custom.sh').read_text()
        block = custom.split('# Keep regulatory reads and writes', 1)[1].split(
            '# Keep mirror selection', 1)[0]
        return subprocess.run(['bash', '-eu', '-c', '# Keep regulatory reads and writes' + block],
                              env=dict(os.environ, DK_OPENWRT=str(base)),
                              capture_output=True, text=True)

    def test_default_target_preserves_nonmatching_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self.prepare(base)
            result = self.apply(base)
            self.assertEqual(result.returncode, 0, result.stderr)
            for mode in ('implicit', 'empty', 'explicit'):
                with self.subTest(mode=mode):
                    default = base / 'default.bin'
                    default.write_bytes(b'default file must remain untouched')
                    target = base / 'caldata.bin'
                    raw = bytearray(0x600)
                    raw[0x34:0x36] = bytes.fromhex('1234')
                    for offset, value in ((0x450, '1234'), (0x458, 'abcd'),
                                          (0x500, '5678'), (0x5a8, '1234')):
                        raw[offset:offset + 2] = bytes.fromhex(value)
                    target.write_bytes(raw)
                    # Only the byte writer is an inert boundary; run the real
                    # helper's selection and BusyBox hexdump/ash semantics.
                    script = '''
hexdump() { busybox hexdump "$@"; }
caldata_patch_data() {
    local target=${4:-$CALDATA_FILE}
    printf '\\000\\000' | dd of="$target" bs=1 seek=$(($2)) conv=notrunc 2>/dev/null
}
. "$1"
shift
ath11k_remove_regdomain "$@"
'''
                    # Relocate only the default filename into our private root.
                    runtime = base / 'runtime.sh'
                    runtime.write_text(source.read_text().replace('/lib/firmware/$FIRMWARE', '${CALDATA_FILE}'))
                    args = {'implicit': [], 'empty': [''], 'explicit': [str(target)]}[mode]
                    default_target = default if mode == 'explicit' else target
                    run = subprocess.run(['busybox', 'ash', '-c', script, 'test', str(runtime), *args],
                                         env=dict(os.environ, CALDATA_FILE=str(default_target)),
                                         input='', capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(run.stderr, '')
                    expected = raw[:]
                    for offset in (0x34, 0x450, 0x5a8):
                        expected[offset:offset + 2] = b'\0\0'
                    self.assertEqual(target.read_bytes(), expected)
                    self.assertEqual(default.read_bytes(), b'default file must remain untouched')

    def test_fix_is_narrow_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = self.prepare(base)
            original = path.read_text()
            path.chmod(0o644)
            for _ in range(2):
                run = self.apply(base)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(path.read_text(), original.replace(
                    '\tlocal target=$1\n', '\tlocal target=${1:-/lib/firmware/$FIRMWARE}\n', 1))
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_duplicate_definitions_rejected_without_writes(self):
        original = FIXTURE.read_text()
        fixed = original.replace('\tlocal target=$1\n',
                                 '\tlocal target=${1:-/lib/firmware/$FIRMWARE}\n', 1)
        for text in (original * 2, fixed + original, fixed + original * 2):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                path = self.prepare(base)
                path.write_text(text)
                self.assertNotEqual(self.apply(base).returncode, 0)
                self.assertEqual(path.read_text(), text)

    def test_drift_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = self.prepare(base)
            text = path.read_text().replace('local target=$1', 'local target=$2')
            path.write_text(text)
            self.assertNotEqual(self.apply(base).returncode, 0)
            self.assertEqual(path.read_text(), text)


if __name__ == '__main__':
    unittest.main()
