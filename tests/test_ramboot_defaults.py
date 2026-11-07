"""Strict content checks use disposable real Git objects, never compilation."""
import copy
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from test_initramfs import checker, fixture_files, payload, chinese_lmo

REG = stat.S_IFREG | 0o644


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True).stdout


def source_fixture(root):
    entries = {
        'package/base-files/files/bin/config_generate': b'official network defaults\n',
        'package/base-files/files/etc/uci-defaults/50-root-passwd': b'official password defaults\n',
        'target/linux/qualcommax/ipq807x/base-files/etc/board.d/02_network': b'official board network\n',
        'package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc': b'official wifi defaults\n',
    }
    for name, data in entries.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    git(root, 'init', '-q'); git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'remote', 'add', 'origin', 'https://github.com/immortalwrt/immortalwrt.git')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'official fixture objects')
    luci = root / 'feeds/luci'; luci.mkdir(parents=True)
    objects = {
        'luci.mk': b'LUCI_LC_ALIAS.zh_Hans=zh-cn\nLUCI_LIBRARYDIR = /usr/lib/lua/luci\n',
        'modules/luci-base/po/zh_Hans/base.po': 'msgid "Flash image..."\nmsgstr "刷写固件…"\n'.encode(),
        'modules/luci-base/root/etc/config/luci': b"config core 'main'\n option lang 'auto'\n",
        'modules/luci-mod-system/root/usr/share/luci/menu.d/luci-mod-system.json': b'{"admin/system":{"title":"System"}}',
    }
    for name, data in objects.items():
        path = luci / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    git(luci, 'init', '-q'); git(luci, 'config', 'user.name', 'Fixture')
    git(luci, 'config', 'user.email', 'fixture@example.invalid')
    git(luci, 'remote', 'add', 'origin', 'https://github.com/immortalwrt/luci.git')
    git(luci, 'add', '.'); git(luci, 'commit', '-qm', 'official luci fixture objects')
    (root / 'tmp').mkdir()
    (root / 'tmp/.targetinfo').write_text('Target: qualcommax/ipq807x\nDefault-Packages: base-files\nTarget-Profile: DEVICE_linksys_homewrk\nTarget-Profile-Packages: wifi-scripts\n')
    files = fixture_files()
    for name, data in entries.items():
        destination = name.split('/base-files/files/')[-1] if '/base-files/files/' in name else name.split('/base-files/')[-1] if '/base-files/' in name else name.split('/files/')[-1]
        files[destination] = REG, data
    files['etc/config/luci'] = REG, objects['modules/luci-base/root/etc/config/luci']
    files['etc/uci-defaults/luci-i18n-base-zh-cn'] = REG, "uci set luci.languages.zh_cn='简体中文 (Simplified Chinese)'; uci commit luci\n".encode()
    files['usr/lib/lua/luci/i18n/base.zh-cn.lmo'] = REG, chinese_lmo()
    files['usr/share/luci/menu.d/luci-mod-system.json'] = REG, objects['modules/luci-mod-system/root/usr/share/luci/menu.d/luci-mod-system.json']
    names = checker.PACKAGES | {'base-files', 'wifi-scripts', 'luci', 'luci-i18n-base-zh-cn'}
    files['lib/apk/db/installed'] = REG, b'\n\n'.join(('P:' + p + '\nV:fixture\nD:' + (' '.join(sorted(checker.PACKAGES)) if p == 'luci' else '')).encode() for p in sorted(names))
    ownership = b''.join(('F:' + str(Path(name).parent) + '\nR:' + Path(name).name + '\n').encode()
                         for name in files if name.startswith(('etc/config/', 'usr/bin/', 'usr/sbin/', 'www/luci-static/')))
    files['lib/apk/db/installed'] = REG, files['lib/apk/db/installed'][1] + b'\n' + ownership
    return files


class RambootDefaultsTests(unittest.TestCase):
    def test_strict_fit_record_and_git_objects_not_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'; root.mkdir(); files = source_fixture(root)
            image = Path(tmp) / 'image.itb'; image.write_bytes(payload(files))
            record = Path(tmp) / 'record.json'
            result = checker.verify(image, record=record, source=root)
            self.assertTrue(record.is_file())
            cli = subprocess.run(['python3', str(checker.__file__), str(image), '--source', str(root), '--record', str(record)],
                                 capture_output=True, text=True)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertEqual(result['default_language'], 'auto')
            self.assertEqual(result['language'], 'zh_cn')
            self.assertIn('bin/config_generate', result['official_defaults'])
            (root / 'package/base-files/files/bin/config_generate').write_text('dirty customization')
            self.assertEqual(checker.verify(image, source=root), result)
            files['bin/config_generate'] = REG, b'dirty customization'
            image.write_bytes(payload(files))
            with self.assertRaisesRegex(ValueError, 'official default'):
                checker.verify(image, source=root)

    def test_missing_native_defaults_and_renamed_orphan_overlays_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); files = source_fixture(root)
            for name in ('bin/config_generate', 'lib/wifi/mac80211.uc', 'etc/board.d/02_network', 'etc/uci-defaults/50-root-passwd'):
                changed = dict(files); del changed[name]
                with self.subTest(missing=name), self.assertRaises(ValueError):
                    checker.verify_official(changed, root)
            for name in ('etc/uci-defaults/88-renamed', 'usr/share/luci/menu.d/renamed.json', 'etc/config/homeproxy', 'usr/bin/sing-box', 'www/luci-static/aurora/asset'):
                changed = dict(files); changed[name] = REG, b'custom overlay'
                with self.subTest(extra=name), self.assertRaises(ValueError):
                    checker.verify_official(changed, root)

    def test_extra_app_and_chinese_nonlanguage_changes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); files = source_fixture(root)
            changed = copy.deepcopy(files)
            mode, data = changed['lib/apk/db/installed']
            changed['lib/apk/db/installed'] = mode, data + b'\n\nP:luci-app-unrequested\nV:fixture\n'
            with self.assertRaisesRegex(ValueError, 'unexpected RAM-system packages'):
                checker.verify_official(changed, root)
            files['etc/config/luci'] = REG, files['etc/config/luci'][1] + b" option mediaurlbase '/luci-static/aurora'\n"
            with self.assertRaisesRegex(ValueError, 'official default'):
                checker.verify_official(files, root)

    def test_native_defaults_cannot_be_deleted_and_residual_packages_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); files = source_fixture(root)
            for package in ('homeproxy', 'sing-box', 'luci-theme-aurora'):
                changed = dict(files)
                mode, data = changed['lib/apk/db/installed']
                changed['lib/apk/db/installed'] = mode, data + b'\n\nP:' + package.encode() + b'\nV:fixture\n'
                with self.subTest(package=package), self.assertRaises(ValueError):
                    checker.verify_official(changed, root)
            changed = dict(files); del changed['usr/share/luci/menu.d/luci-mod-system.json']
            with self.assertRaises(ValueError): checker.verify_official(changed, root)

    def test_cli_requires_source_before_creating_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            image, record = Path(tmp) / 'image.itb', Path(tmp) / 'record.json'
            image.write_bytes(payload())
            result = subprocess.run(['python3', str(Path(checker.__file__)), str(image), '--record', str(record)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--source', result.stderr)
            self.assertFalse(record.exists())
