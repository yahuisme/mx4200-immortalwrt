"""Real FIT/gzip/Zstd/newc validation with explicit harmless payloads."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_initramfs', ROOT / 'scripts/check_initramfs.py')
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def chinese_lmo():
    data = '刷写固件'.encode()
    data += b'\0' * (-len(data) % 4)
    return data + struct.pack('>5I', 1, 1, 0, len('刷写固件'.encode()), len(data))


def fixture_files():
    files = {name: (stat.S_IFREG | 0o755, b'fixture, not executable firmware') for name in checker.REQUIRED}
    files['etc/rc.d/S50uhttpd'] = (stat.S_IFLNK | 0o777, b'../init.d/uhttpd')
    files['lib/apk/db/installed'] = (stat.S_IFREG | 0o644,
        b'\n\n'.join(b'P:' + name.encode() + b'\nV:fixture' for name in sorted(checker.PACKAGES)))
    return files


def cpio(files, trailer=True):
    result = bytearray()
    for name, (mode, payload) in list(files.items()) + ([('TRAILER!!!', (0, b''))] if trailer else []):
        encoded = name.encode() + b'\0'
        values = (0, mode, 0, 0, 1, 0, len(payload), 0, 0, 0, 0, len(encoded), 0)
        result.extend(b'070701' + ''.join(f'{v:08x}' for v in values).encode() + encoded)
        result.extend(b'\0' * (-len(result) % 4))
        result.extend(payload)
        result.extend(b'\0' * (-len(result) % 4))
    return bytes(result)


def fit(kernel, compression=b'gzip\0'):
    strings = b'data\0type\0compression\0'
    tree = bytearray()
    def node(name):
        tree.extend(struct.pack('>I', 1) + name.encode() + b'\0')
        tree.extend(b'\0' * (-len(tree) % 4))
    def prop(offset, value):
        tree.extend(struct.pack('>III', 3, len(value), offset) + value)
        tree.extend(b'\0' * (-len(tree) % 4))
    node(''); node('images'); node('kernel-1')
    prop(0, gzip.compress(kernel)); prop(5, b'kernel\0'); prop(10, compression)
    tree.extend(struct.pack('>IIII', 2, 2, 2, 9))
    start = 56
    header = struct.pack('>10I', 0xd00dfeed, start + len(tree) + len(strings), start,
                         start + len(tree), 40, 17, 16, 0, len(strings), len(tree))
    return header + b'\0' * 16 + tree + strings


def payload(files=None, trailer=True):
    raw = cpio(fixture_files() if files is None else files, trailer)
    compressed = subprocess.run(['zstd', '-q', '-c'], input=raw, capture_output=True, check=True).stdout
    return fit(b'harmless ARM kernel stand-in\0' + compressed + b'trailing kernel data')


class InitramfsTests(unittest.TestCase):
    def test_complete_fit_gzip_zstd_cpio_and_record(self):
        data = payload()
        with tempfile.TemporaryDirectory() as tmp:
            image, record = Path(tmp) / 'homewrk.itb', Path(tmp) / 'record.json'
            image.write_bytes(data)
            result = checker.verify(image, record)
            self.assertTrue(result['complete_cpio'])
            self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(json.loads(record.read_text()), result)

    def test_chinese_dictionary_and_default_language(self):
        files = fixture_files()
        files['usr/lib/lua/luci/i18n/base.zh-cn.lmo'] = stat.S_IFREG | 0o644, chinese_lmo()
        files['etc/config/luci'] = stat.S_IFREG | 0o644, b"config core 'main'\n\toption lang 'auto'\n"
        files['etc/uci-defaults/luci-i18n-base-zh-cn'] = stat.S_IFREG | 0o644, "uci set luci.languages.zh_cn='简体中文 (Simplified Chinese)'; uci commit luci\n".encode()
        self.assertEqual(checker.verify_chinese(files)['language'], 'zh_cn')
        for path in ('usr/lib/lua/luci/i18n/base.zh-cn.lmo', 'etc/config/luci'):
            broken = dict(files); del broken[path]
            with self.subTest(path=path), self.assertRaises(ValueError):
                checker.verify_chinese(broken)
        files['etc/config/luci'] = stat.S_IFREG | 0o644, b"config core main\n option lang en\n"
        with self.assertRaises(ValueError): checker.verify_chinese(files)

    def test_nonempty_fake_chinese_dictionary_is_rejected(self):
        files = fixture_files()
        files['etc/config/luci'] = stat.S_IFREG | 0o644, b'config core main\n option lang auto\n'
        files['etc/uci-defaults/luci-i18n-base-zh-cn'] = stat.S_IFREG | 0o644, "uci set luci.languages.zh_cn='简体中文 (Simplified Chinese)'; uci commit luci\n".encode()
        files['usr/lib/lua/luci/i18n/base.zh-cn.lmo'] = stat.S_IFREG | 0o644, b'not a compiled dictionary'
        with self.assertRaisesRegex(ValueError, 'dictionary'):
            checker.verify_chinese(files)

    def test_kernel_generated_symlink_payload_may_include_nul(self):
        files = fixture_files()
        files['etc/rc.d/S50uhttpd'] = stat.S_IFLNK | 0o777, b'../init.d/uhttpd\0'
        self.assertTrue(checker.verify_files(files)['complete_cpio'])

    def test_every_required_path_and_package_is_enforced(self):
        for name in checker.REQUIRED:
            files = fixture_files(); del files[name]
            with self.subTest(path=name), self.assertRaises(ValueError):
                checker.verify_files(files)
        for package in checker.PACKAGES:
            files = fixture_files()
            mode, installed = files['lib/apk/db/installed']
            files['lib/apk/db/installed'] = mode, installed.replace(b'P:' + package.encode() + b'\n', b'P:absent\n')
            with self.subTest(package=package), self.assertRaises(ValueError):
                checker.verify_files(files)

    def test_executable_types_and_enabled_service_are_required(self):
        for name in checker.REQUIRED:
            files = fixture_files(); files[name] = stat.S_IFDIR | 0o755, b'not a file'
            with self.subTest(path=name), self.assertRaises(ValueError): checker.verify_files(files)
        for name in ('www/cgi-bin/luci', 'usr/sbin/uhttpd', 'etc/init.d/uhttpd'):
            files = fixture_files(); files[name] = stat.S_IFREG | 0o644, b'not executable'
            with self.subTest(path=name), self.assertRaises(ValueError): checker.verify_files(files)
        files = fixture_files(); files['etc/rc.d/S50uhttpd'] = stat.S_IFLNK | 0o777, b'../init.d/disabled'
        with self.assertRaises(ValueError): checker.verify_files(files)

    def test_dangling_program_links_and_regular_startup_link_rejected(self):
        for name in ('www/cgi-bin/luci', 'usr/sbin/uhttpd', 'etc/init.d/uhttpd'):
            files = fixture_files()
            files[name] = stat.S_IFLNK | 0o777, b'/missing/program'
            with self.subTest(path=name), tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / 'image.itb'
                image.write_bytes(payload(files))
                with self.assertRaisesRegex(ValueError, 'invalid LuCI RAM-system file'):
                    checker.verify(image)
        files = fixture_files()
        files['etc/rc.d/S50uhttpd'] = stat.S_IFREG | 0o755, b'../init.d/uhttpd'
        with self.assertRaisesRegex(ValueError, 'invalid LuCI RAM-system file'):
            checker.verify_files(files)

    def test_truncation_bad_fit_and_incomplete_cpio_rejected(self):
        good = payload()
        cases = [b'', good[:20], b'bad!' + good[4:], good[:-12], payload(trailer=False),
                 fit(b'kernel without initramfs'), fit(b'', compression=b'none\0')]
        for data in cases:
            with self.subTest(size=len(data)), tempfile.TemporaryDirectory() as tmp:
                image = Path(tmp) / 'image.itb'; image.write_bytes(data)
                with self.assertRaises((ValueError, OSError, EOFError, struct.error)): checker.verify(image)

    def test_nonregular_empty_symlink_input_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'image.itb'; image.write_bytes(payload())
            link = root / 'link.itb'; link.symlink_to(image)
            for path in (link, root, root / 'missing'):
                with self.subTest(path=path), self.assertRaises(ValueError): checker.verify(path)

    def test_cpio_bounds_trailer_and_path_safety(self):
        raw = cpio(fixture_files())
        for data in (raw[:-20], raw + b'invalid trailing data', b'badnew' + raw[6:],
                     cpio({'../escape': (stat.S_IFREG | 0o644, b'x')})):
            with self.subTest(size=len(data)), self.assertRaises(ValueError): checker.cpio_files(data)

    def test_production_stage_checks_real_built_image_before_copy(self):
        import yaml
        steps = yaml.safe_load((ROOT / '.github/workflows/MX4200.yml').read_text())['jobs']['build']['steps']
        body = next(s['run'] for s in steps if s.get('id') == 'stage')
        self.assertLess(body.index('/cache-scripts/check_initramfs.py'), body.index('scripts/release_images.py stage'))
        self.assertNotIn('scripts/official_initramfs.py', body)
        self.assertIn('CONFIG_TARGET_ROOTFS_INITRAMFS=y', (ROOT / 'user/ramboot/config.diff').read_text())
        self.assertIn('CONFIG_TARGET_ROOTFS_INITRAMFS=n', (ROOT / 'user/default/config.diff').read_text())
        ramboot = (ROOT / 'scripts/build_ramboot.sh').read_text()
        self.assertIn('--source "$ram"', ramboot)
