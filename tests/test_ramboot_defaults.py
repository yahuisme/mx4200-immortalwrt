"""Strict content checks use disposable real Git objects, never compilation."""
import copy
import os
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
        'package/network/services/dropbear/Makefile': b'define Package/dropbear\n ALTERNATIVES:=100:/usr/bin/ssh-keygen:/usr/sbin/dropbear\n $(if $(CONFIG_DROPBEAR_SCP),ALTERNATIVES+= \\\n 100:/usr/bin/scp:/usr/sbin/dropbear,)\n $(if $(CONFIG_DROPBEAR_DBCLIENT),ALTERNATIVES+= \\\n 100:/usr/bin/ssh:/usr/sbin/dropbear,)\nendef\ndefine Package/dropbear/install\n $(INSTALL_CONF) ./files/dropbear.config $(1)/etc/config/dropbear\nendef\n',
        'package/network/services/dropbear/files/dropbear.config': b"config dropbear main\n option Port '22'\n",
        'package/network/services/dnsmasq/Makefile': b'define Package/dnsmasq-full\nendef\ndefine Package/dnsmasq/install\n $(INSTALL_CONF) ./files/dhcp.conf $(1)/etc/config/dhcp\nendef\n',
        'package/network/services/dnsmasq/files/dhcp.conf': b"config dhcp lan\n option ignore '0'\n",
        'package/libs/uclient/Makefile': b'define Package/uclient-fetch\n ALTERNATIVES:=200:/usr/bin/wget:/bin/uclient-fetch\nendef\n',
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
        if '/base-files/' not in name and not name.endswith('/mac80211.uc'):
            continue
        destination = name.split('/base-files/files/')[-1] if '/base-files/files/' in name else name.split('/base-files/')[-1] if '/base-files/' in name else name.split('/files/')[-1]
        files[destination] = REG, data
    files['etc/config/dhcp'] = REG, entries['package/network/services/dnsmasq/files/dhcp.conf']
    files['etc/config/dropbear'] = REG, entries['package/network/services/dropbear/files/dropbear.config']
    files['usr/sbin/dropbear'] = stat.S_IFREG | 0o755, b'fixture executable'
    files['bin/uclient-fetch'] = stat.S_IFREG | 0o755, b'fixture executable'
    for name in ('scp', 'ssh', 'ssh-keygen'):
        files['usr/bin/' + name] = stat.S_IFLNK | 0o777, b'/usr/sbin/dropbear\0'
    files['usr/bin/wget'] = stat.S_IFLNK | 0o777, b'/bin/uclient-fetch\0'
    files['lib/apk/packages/dropbear.alternatives'] = REG, b'100:/usr/bin/ssh-keygen:/usr/sbin/dropbear 100:/usr/bin/scp:/usr/sbin/dropbear 100:/usr/bin/ssh:/usr/sbin/dropbear\n'
    files['lib/apk/packages/uclient-fetch.alternatives'] = REG, b'200:/usr/bin/wget:/bin/uclient-fetch\n'
    files['etc/config/luci'] = REG, objects['modules/luci-base/root/etc/config/luci']
    files['etc/uci-defaults/luci-i18n-base-zh-cn'] = REG, "uci set luci.languages.zh_cn='简体中文 (Simplified Chinese)'; uci commit luci\n".encode()
    files['usr/lib/lua/luci/i18n/base.zh-cn.lmo'] = REG, chinese_lmo()
    files['usr/share/luci/menu.d/luci-mod-system.json'] = REG, objects['modules/luci-mod-system/root/usr/share/luci/menu.d/luci-mod-system.json']
    ownership = {
        'dropbear': ['etc/config/dropbear', 'usr/sbin/dropbear'],
        'dnsmasq-full': ['etc/config/dhcp'],
        'uclient-fetch': ['bin/uclient-fetch'],
        'luci-mod-system': ['www/luci-static/resources/view/system/flash.js'],
        'uhttpd': ['usr/sbin/uhttpd'],
        'luci': ['etc/config/luci'],
    }
    names = checker.PACKAGES | {'base-files', 'wifi-scripts', 'luci', 'luci-i18n-base-zh-cn'} | set(ownership)
    records = []
    for package in sorted(names):
        row = 'P:' + package + '\nV:fixture\nD:' + (' '.join(sorted(names - {'luci'})) if package == 'luci' else '')
        for name in ownership.get(package, []):
            row += '\nF:' + str(Path(name).parent) + '\nR:' + Path(name).name
        records.append(row.encode())
    files['lib/apk/db/installed'] = REG, b'\n\n'.join(records) + b'\n'
    return files


@unittest.skipUnless(os.environ.get('MX_RAM_ARCHIVE') and os.environ.get('MX_RAM_SOURCE')
                     and os.environ.get('MX_LUCI_CONTROL'), 'real official FIT/source controls not supplied')
class OfficialArchiveTests(unittest.TestCase):
    def test_native_archive_assembly_and_negative_mutations(self):
        source = Path(os.environ['MX_RAM_SOURCE'])
        native = checker.ram_files(checker.kernel_data(Path(os.environ['MX_RAM_ARCHIVE']).read_bytes()))
        control = checker.ram_files(checker.kernel_data(Path(os.environ['MX_LUCI_CONTROL']).read_bytes()))
        checker.verify_files(control)  # Real parser positive, not pristine policy.
        with self.assertRaises(ValueError): checker.verify_files(native)
        files = dict(native)
        for name in checker.REQUIRED:
            files[name] = control[name]
        for name in ('usr/lib/lua/luci/i18n/base.zh-cn.lmo', 'etc/uci-defaults/luci-i18n-base-zh-cn'):
            files[name] = control[name]
        for destination, original in (
            ('etc/config/luci', 'modules/luci-base/root/etc/config/luci'),
            ('usr/share/luci/menu.d/luci-mod-system.json', 'modules/luci-mod-system/root/usr/share/luci/menu.d/luci-mod-system.json'),
        ):
            files[destination] = REG, git(source / 'feeds/luci', 'show', 'HEAD:' + original)
        # Offline assembly only. Preserve native DB records byte-for-byte; add
        # ownership for newly added payload files, NEVER the native alternatives.
        db_mode, db = native['lib/apk/db/installed']
        records = checker.installed_records(native)
        added = {
            'luci': ('luci-mod-system uhttpd rpcd', ['etc/config/luci']),
            'luci-mod-system': ('', ['www/cgi-bin/luci', 'www/luci-static/resources/view/system/flash.js',
                                    'usr/share/luci/menu.d/luci-mod-system.json']),
            'uhttpd': ('', ['usr/sbin/uhttpd', 'etc/init.d/uhttpd']),
            'luci-i18n-base-zh-cn': ('', ['usr/lib/lua/luci/i18n/base.zh-cn.lmo',
                                       'etc/uci-defaults/luci-i18n-base-zh-cn']),
        }
        for package, (dependencies, paths) in added.items():
            self.assertNotIn(package, records)
            row = '\n\nP:' + package + '\nV:offline-assembly\nD:' + dependencies + '\n'
            row += ''.join('F:' + str(Path(path).parent) + '\nR:' + Path(path).name + '\n' for path in paths)
            db += row.encode()
        files['lib/apk/db/installed'] = db_mode, db
        files.pop('etc/uci-defaults/51-attendedsysupgrade-owut', None)
        # The downloaded buildbot snapshot selects owut; use a private targetinfo
        # extension, not a change to the production official package policy.
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'source'; private.mkdir()
            (private / '.git').symlink_to(source / '.git', target_is_directory=True)
            (private / 'feeds').symlink_to(source / 'feeds', target_is_directory=True)
            (private / 'tmp').mkdir()
            metadata = (source / 'tmp/.targetinfo').read_text()
            (private / 'tmp/.targetinfo').write_text(metadata.replace('Default-Packages: ', 'Default-Packages: owut '))
            image = Path(tmp) / 'official-archive-assembly.itb'; image.write_bytes(payload(files))
            result = checker.verify(image, source=private)
            self.assertEqual(result['default_language'], 'auto')
            for path in ('etc/config/dhcp', 'etc/config/dropbear'):
                self.assertIn(path, result['official_defaults'])
            if os.environ.get('MX_RAM_ASSEMBLY_OUT'):
                Path(os.environ['MX_RAM_ASSEMBLY_OUT']).write_bytes(image.read_bytes())
            cases = {
                'changed-link': ('usr/bin/ssh', (stat.S_IFLNK | 0o777, b'/bin/evil')),
                'regular-link': ('usr/bin/wget', (REG, b'/bin/uclient-fetch')),
                'unrequested-alternative': ('lib/apk/packages/dropbear.alternatives',
                                           (REG, b'100:/usr/bin/evil:/usr/sbin/dropbear')),
                'uninstalled-alternative': ('lib/apk/packages/evil.alternatives',
                                           (REG, b'100:/usr/bin/evil:/usr/sbin/dropbear')),
                'dhcp-mutation': ('etc/config/dhcp', (REG, files['etc/config/dhcp'][1] + b'\nconfig dhcp lan\n option ignore 1\n')),
                'dropbear-mutation': ('etc/config/dropbear', (REG, files['etc/config/dropbear'][1] + b'\nconfig dropbear\n option Port 2222\n')),
                'extra-app': ('lib/apk/db/installed', (db_mode, db + b'\n\nP:luci-app-unrequested\nV:fixture\n')),
            }
            for label, (name, value) in cases.items():
                changed = dict(files); changed[name] = value
                image.write_bytes(payload(changed))
                error = ('official default.*' + name if label.endswith('mutation') else
                         'unexpected RAM-system packages' if label == 'extra-app' else
                         'unauthenticated official alternatives' if label.endswith('alternative') else
                         'official alternative link')
                with self.subTest(mutation=label), self.assertRaisesRegex(ValueError, error):
                    checker.verify(image, source=private)
            # Genuine postinst links stay absent from APK payload ownership.
            directory = ''; owned = set()
            for line in db.decode().splitlines():
                if line.startswith('F:'): directory = line[2:]
                elif line.startswith('R:'): owned.add(directory + '/' + line[2:])
            for name in ('scp', 'ssh', 'ssh-keygen', 'wget'):
                self.assertNotIn('usr/bin/' + name, owned)
                self.assertEqual(files['usr/bin/' + name], native['usr/bin/' + name])


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

    def test_native_alternatives_require_installed_source_and_exact_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); files = source_fixture(root)
            checker.verify_official(files, root)
            for name in ('scp', 'ssh', 'ssh-keygen', 'wget'):
                path = 'usr/bin/' + name
                for value in ((REG, files[path][1]), (stat.S_IFLNK | 0o777, b'/bin/evil'),
                              (stat.S_IFLNK | 0o777, files[path][1] + b'\0')):
                    changed = dict(files); changed[path] = value
                    with self.subTest(path=path, value=value), self.assertRaisesRegex(ValueError, 'alternative link'):
                        checker.verify_official(changed, root)
            for path, value in (
                ('lib/apk/packages/dropbear.alternatives', b'100:/usr/bin/ssh:/bin/evil'),
                ('lib/apk/packages/dropbear.alternatives', b'100:/usr/bin/unrequested:/usr/sbin/dropbear'),
                ('lib/apk/packages/not-installed.alternatives', b'100:/usr/bin/ssh:/usr/sbin/dropbear'),
                ('lib/apk/packages/uclient-fetch.alternatives', b'200:/usr/bin/ssh:/usr/sbin/dropbear'),
            ):
                changed = dict(files); changed[path] = REG, value
                with self.subTest(path=path, value=value), self.assertRaisesRegex(ValueError, 'unauthenticated'):
                    checker.verify_official(changed, root)
            changed = dict(files); del changed['lib/apk/packages/dropbear.alternatives']
            with self.assertRaisesRegex(ValueError, 'unowned'):
                checker.verify_official(changed, root)
            # A forged ownership row must not bypass alternative link validation.
            changed = dict(files); changed['usr/bin/ssh'] = REG, b'forged'
            mode, db = changed['lib/apk/db/installed']
            changed['lib/apk/db/installed'] = mode, db + b'F:usr/bin\nR:ssh\n'
            with self.assertRaisesRegex(ValueError, 'alternative link'):
                checker.verify_official(changed, root)
            (root / 'package/libs/uclient/Makefile').write_text('dirty worktree alternative')
            checker.verify_official(files, root)

    def test_owned_package_configs_compare_committed_recipe_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); files = source_fixture(root)
            result = checker.verify_official(files, root)
            for name, value in (('etc/config/dhcp', b"config dhcp lan\n option ignore 1\n"),
                                ('etc/config/dropbear', b"config dropbear main\n option Port 2222\n")):
                self.assertIn(name, result['official_defaults'])
                changed = dict(files); changed[name] = REG, value
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'official default'):
                    checker.verify_official(changed, root)
                del changed[name]
                with self.subTest(missing=name), self.assertRaisesRegex(ValueError, 'official default'):
                    checker.verify_official(changed, root)
            files['etc/config/dropbear'] = REG, b'# spacing/quoting only\nconfig dropbear "main"\n option Port 22\n'
            checker.verify_official(files, root)
            (root / 'package/network/services/dropbear/files/dropbear.config').write_bytes(b'config dropbear main\n option Port 2222\n')
            checker.verify_official(files, root)
            files['etc/config/dropbear'] = REG, b'config dropbear main\n option Port 2222\n'
            with self.assertRaisesRegex(ValueError, 'official default'):
                checker.verify_official(files, root)

    def test_cli_requires_source_before_creating_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            image, record = Path(tmp) / 'image.itb', Path(tmp) / 'record.json'
            image.write_bytes(payload())
            result = subprocess.run(['python3', str(Path(checker.__file__)), str(image), '--record', str(record)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--source', result.stderr)
            self.assertFalse(record.exists())
