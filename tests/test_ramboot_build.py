"""Exercise the RAM production shell with real Git objects, never real make.

Only absolute container paths and external build/inspection boundaries are
relocated/stubbed. The official-object checkout, minimal-intent checker, native
revision and metadata merger all execute their real production code.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any

from revision_fixture import ROOT, history, commit, git, revision
from test_dual_publish import INITRAMFS


class RambootBuildTests(unittest.TestCase):
    def fixture(self, base, fault=''):
        source, ram = base / 'main', base / 'ramboot'
        history(source)
        (source / 'feeds.conf.default').write_text('src-git luci https://github.com/immortalwrt/luci.git\n')
        (source / 'official-default').write_text('192.168.1.1\n')
        feeds = source / 'scripts/feeds'
        feeds.write_text('#!/bin/sh\nprintf "feeds %s\\n" "$*" >> "$CALLS"\n')
        feeds.chmod(0o755)
        head = commit(source, 'official source and defaults')
        # Native getver requires tracking history even when the source is local.
        git(source, 'remote', 'add', 'origin', 'https://github.com/immortalwrt/immortalwrt.git')
        git(source, 'update-ref', 'refs/remotes/origin/master', head)
        git(source, 'config', 'branch.master.remote', 'origin')
        git(source, 'config', 'branch.master.merge', 'refs/heads/master')
        feed = source / 'feeds/luci'
        history(feed)
        (feed / 'official-luci').write_text('official package recipe\n')
        commit(feed, 'official LuCI input')
        # Deliberately dirty formal source/feed, rootfs overlays and staging.
        (source / 'official-default').write_text('192.168.10.1\n')
        (feed / 'official-luci').write_text('custom package recipe\n')
        for name in ('files/etc/custom', '.external-packages/custom',
                     'staging_dir/host/custom-tool', 'build_dir/custom-stamp'):
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('must not reach RAM')
        (feed / 'untracked-custom').write_text('must not reach RAM')
        (source / 'feeds.conf').write_text('src-git custom https://example.invalid/custom\n')
        (source / '.config').write_text((ROOT / 'user/default/config.diff').read_text())
        user = base / 'user/ramboot'
        user.mkdir(parents=True)
        (user / 'config.diff').write_bytes((ROOT / 'user/ramboot/config.diff').read_bytes())
        output = base / 'output/targets/qualcommax/ipq807x'
        output.mkdir(parents=True)
        data = {'target': 'qualcommax/ipq807x', 'version_code': revision(source), 'profiles': {}}
        for device in ('mx4200v1', 'mx4200v2', 'mx4300', 'homewrk'):
            images = []
            for kind in ('factory', 'sysupgrade'):
                ext = 'ubi' if device == 'homewrk' and kind == 'factory' else 'bin'
                name = f'immortalwrt-qualcommax-ipq807x-linksys_{device}-squashfs-{kind}.{ext}'
                (output / name).write_bytes(b'fixture flash image, not firmware')
                images.append(dict(name=name, type=kind, filesystem='squashfs', size=(output/name).stat().st_size))
            data['profiles']['linksys_' + device] = dict(images=images)
        (output / 'profiles.json').write_text(json.dumps(data))
        record = base / 'record'
        record.mkdir()
        tools = base / 'tools'
        tools.mkdir()
        make = tools / 'make'
        make.write_text(f'#!{sys.executable}\n' + '''import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['CALLS'],'a') as stream: stream.write('make '+ ' '.join(args)+'\\n')
fault=os.environ.get('FAULT','')
phase='defconfig' if args[0]=='defconfig' else 'download' if args[0]=='download' else 'world'
if fault==phase: sys.exit(29)
if phase=='defconfig':
    config=Path('.config'); text=config.read_text()
    host='CONFIG_CCACHE=y' in text
    if host and fault=='second-defconfig': sys.exit(29)
    # Simulated native output only: no make/conf/compiler is executed locally.
    text+='CONFIG_TARGET_ROOTFS_SQUASHFS=y\\nCONFIG_BUSYBOX_DEFAULT_PING=y\\nCONFIG_VERSION_DIST="ImmortalWrt"\\n'
    if host:
        text+='CONFIG_GOLANG_BUILD_CACHE_DIR=""\\n# CONFIG_GOLANG_MOD_CACHE_WORLD_READABLE is not set\\n'
        mutations={'extra-app':'CONFIG_PACKAGE_luci-app-homeproxy=y\\n',
                   'version-drift':'CONFIG_VERSION_DIST="ProjectRAM"',
                   'rootfs-drift':'# CONFIG_TARGET_ROOTFS_SQUASHFS is not set',
                   'busybox-drift':'# CONFIG_BUSYBOX_DEFAULT_PING is not set'}
        if fault=='extra-app': text+=mutations[fault]
        if fault in ('version-drift','rootfs-drift','busybox-drift'):
            original={'version-drift':'CONFIG_VERSION_DIST="ImmortalWrt"',
                      'rootfs-drift':'CONFIG_TARGET_ROOTFS_SQUASHFS=y',
                      'busybox-drift':'CONFIG_BUSYBOX_DEFAULT_PING=y'}[fault]
            text=text.replace(original,mutations[fault])
        baseline=Path(os.environ['RECORD'])/'ramboot-baseline.config'
        if fault=='baseline-tamper': baseline.write_text(baseline.read_text()+'# tampered\\n')
        if fault=='baseline-identity':
            meta=Path(str(baseline)+'.json'); proof=json.loads(meta.read_text())
            proof['source_sha']='0'*40; meta.write_text(json.dumps(proof))
    else:
        text+='CONFIG_GOLANG_BUILD_BOOTSTRAP=y\\nCONFIG_GOLANG_EXTERNAL_BOOTSTRAP_ROOT=""\\n'
    config.write_text(text)
if phase=='download' and fault=='download-config-drift':
    with Path('.config').open('a') as stream: stream.write('CONFIG_PACKAGE_unexpected-app=y\\n')
if phase=='world':
    if fault=='world-config-drift':
        with Path('.config').open('a') as stream: stream.write('CONFIG_PACKAGE_unexpected-app=y\\n')
    import subprocess
    rev=subprocess.check_output(['./scripts/getver.sh'],text=True).strip()
    out=Path('bin/targets/qualcommax/ipq807x'); out.mkdir(parents=True)
    name='immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb'
    image=out/name; image.write_bytes(b'fixture RAM image, not firmware')
    (out/'profiles.json').write_text(json.dumps(dict(target='qualcommax/ipq807x',version_code=rev,profiles=dict(linksys_homewrk=dict(images=[dict(name=name,type='kernel',filesystem='initramfs',size=image.stat().st_size)])))))
''')
        make.chmod(0o755)
        python = tools / 'python3'
        python.write_text(f'#!{sys.executable}\n' + '''import hashlib,json,os,sys
from pathlib import Path
script=Path(sys.argv[1]).name
if script=='check_go.py': sys.exit(0) # Host-tool boundary, not a Go capability claim.
if script=='check_initramfs.py':
    if os.environ.get('FAULT')=='inspection': sys.exit(31)
    image=Path(sys.argv[2]); record=Path(sys.argv[sys.argv.index('--record')+1])
    assert sys.argv[3]=='--source' and Path(sys.argv[4])==Path.cwd()
    record.write_text(json.dumps(dict(name=image.name,size=image.stat().st_size,sha256=hashlib.sha256(image.read_bytes()).hexdigest(),complete_cpio=True,fixture_inspection=True)))
else: os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
''')
        python.chmod(0o755)
        shell = (ROOT / 'scripts/build_ramboot.sh').read_text()
        for old, new in (('/bld/ramboot', str(ram)), ('/cache-scripts/', str(ROOT / 'scripts') + '/'),
                         ('/build-record/', str(record) + '/'), ('/dlcache', str(base / 'downloads')),
                         ('/ghcache', str(base / 'ccache'))):
            shell = shell.replace(old, new)
        env = dict(os.environ, DK_OPENWRT=str(source), DK_USER=str(base / 'user'),
                   DK_BIN=str(base / 'output'), PATH=str(tools) + os.pathsep + os.environ['PATH'],
                   CALLS=str(base / 'calls'), FAULT=fault, RECORD=str(record),
                   GIT_CONFIG_GLOBAL=str(base / 'gitconfig'), GIT_CONFIG_NOSYSTEM='1')
        return shell, env, source, ram, output, record

    def test_real_shell_clones_committed_objects_and_merges_only_homewrk_ram(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            shell, env, source, ram, output, record = self.fixture(base)
            result = subprocess.run(['bash', '-c', shell], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((ram / 'official-default').read_text(), '192.168.1.1\n')
            self.assertEqual((ram / 'feeds/luci/official-luci').read_text(), 'official package recipe\n')
            self.assertEqual((source / 'official-default').read_text(), '192.168.10.1\n')
            for path in ('files', '.external-packages', 'staging_dir', 'build_dir', 'feeds/luci/untracked-custom'):
                self.assertFalse((ram / path).exists(), path)
            self.assertEqual(git(ram, 'rev-parse', 'HEAD'), git(source, 'rev-parse', 'HEAD'))
            self.assertEqual(revision(ram), revision(source))
            self.assertEqual(git(ram / 'feeds/luci', 'rev-parse', 'HEAD'), git(source / 'feeds/luci', 'rev-parse', 'HEAD'))
            self.assertEqual((ram / 'dl').readlink(), base / 'downloads')
            proof = json.loads((record / 'ramboot.json').read_text())
            self.assertTrue(proof['pristine'])
            self.assertEqual(proof['customization'], 'Chinese LuCI only')
            metadata = json.loads((output / 'profiles.json').read_text())
            rows = [image for profile in metadata['profiles'].values() for image in profile['images']]
            self.assertEqual(len(rows), 9)
            self.assertEqual([row['name'] for row in rows if row['filesystem'] == 'initramfs'], [INITRAMFS])
            self.assertEqual((output / INITRAMFS).read_bytes(), (ram / 'bin/targets/qualcommax/ipq807x' / INITRAMFS).read_bytes())
            self.assertEqual(hashlib.sha256((output / INITRAMFS).read_bytes()).hexdigest(),
                             json.loads((record / 'initramfs.json').read_text())['sha256'])
            calls = (base / 'calls').read_text().splitlines()
            self.assertEqual(calls[:5], ['feeds update -i', 'feeds install -a', 'make defconfig', 'make defconfig', 'make download -j8'])
            self.assertEqual(len([row for row in calls if row.startswith('make ')]), 4)
            baseline = record / 'ramboot-baseline.config'
            self.assertTrue(baseline.is_file())
            self.assertNotIn('CONFIG_CCACHE=y', baseline.read_text())
            self.assertEqual(proof['baseline_sha256'], hashlib.sha256(baseline.read_bytes()).hexdigest())
            self.assertEqual(proof['baseline_resolver'], 'make defconfig')

    def test_merger_rejects_incompatible_or_duplicate_ram_without_overwriting_main(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('stage_ramboot_under_test', ROOT / 'scripts/stage_ramboot.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for case in ('target', 'revision', 'profile', 'type', 'filesystem', 'size',
                     'missing', 'empty', 'symlink', 'duplicate', 'preexisting', 'dangling-destination'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                source, target = base / 'source', base / 'target'
                source.mkdir(); target.mkdir()
                image = source / INITRAMFS
                image.write_bytes(b'fixture-not-firmware')
                entry: dict[str, Any] = dict(name=INITRAMFS, type='kernel', filesystem='initramfs', size=image.stat().st_size)
                data: dict[str, Any] = dict(target='qualcommax/ipq807x', version_code='r123-abcdef',
                            profiles={'linksys_homewrk': {'images': [entry]}})
                main: dict[str, Any] = dict(target=data['target'], version_code=data['version_code'],
                            profiles={'linksys_homewrk': {'images': []}})
                if case == 'target': data['target'] = 'other/target'
                if case == 'revision': data['version_code'] = 'r124-abcdef'
                if case == 'profile': data['profiles']['linksys_mx4300'] = {'images': []}
                if case == 'type': entry['type'] = 'sysupgrade'
                if case == 'filesystem': entry['filesystem'] = 'squashfs'
                if case == 'size': entry['size'] += 1
                if case == 'missing': image.unlink()
                if case == 'empty': image.write_bytes(b'')
                if case == 'symlink':
                    image.rename(source / 'payload'); image.symlink_to('payload')
                if case == 'duplicate': main['profiles']['linksys_homewrk']['images'].append(entry)
                if case == 'preexisting': (target / INITRAMFS).write_bytes(b'must preserve')
                if case == 'dangling-destination': (target / INITRAMFS).symlink_to(base / 'outside')
                (source / 'profiles.json').write_text(json.dumps(data))
                (target / 'profiles.json').write_text(json.dumps(main))
                before = (target / 'profiles.json').read_bytes()
                with self.assertRaises(ValueError):
                    module.stage(source, target)
                self.assertEqual((target / 'profiles.json').read_bytes(), before)
                if case == 'preexisting': self.assertEqual((target / INITRAMFS).read_bytes(), b'must preserve')
                else: self.assertFalse((target / INITRAMFS).exists())
                self.assertFalse((base / 'outside').exists())

    def test_production_rejects_resolved_target_drift_before_download(self):
        for fault in ('extra-app', 'version-drift', 'rootfs-drift', 'busybox-drift', 'second-defconfig',
                      'baseline-tamper', 'baseline-identity'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                shell, env, source, ram, output, record = self.fixture(base, fault)
                before = (output / 'profiles.json').read_bytes()
                result = subprocess.run(['bash', '-c', shell], env=env, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('make download', (base / 'calls').read_text())
                self.assertEqual(before, (output / 'profiles.json').read_bytes())
                self.assertFalse((record / 'ramboot.json').exists())
                self.assertFalse((output / INITRAMFS).exists())

    def test_download_config_drift_is_rechecked_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            shell, env, source, ram, output, record = self.fixture(base, 'download-config-drift')
            result = subprocess.run(['bash', '-c', shell], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('make -j', (base / 'calls').read_text())
            self.assertFalse((record / 'initramfs.json').exists())

    def test_world_config_drift_is_rechecked_before_inspection_and_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            shell, env, source, ram, output, record = self.fixture(base, 'world-config-drift')
            before = (output / 'profiles.json').read_bytes()
            result = subprocess.run(['bash', '-c', shell], env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(before, (output / 'profiles.json').read_bytes())
            self.assertFalse((record / 'initramfs.json').exists())
            self.assertFalse((output / INITRAMFS).exists())

    def test_build_or_inspection_failure_never_merges_temporary_image(self):
        for fault in ('defconfig', 'download', 'world', 'inspection'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                shell, env, source, ram, output, record = self.fixture(base, fault)
                before = (output / 'profiles.json').read_bytes()
                result = subprocess.run(['bash', '-c', shell], env=env, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((output / 'profiles.json').read_bytes(), before)
                self.assertFalse((output / INITRAMFS).exists())
                self.assertFalse((record / 'initramfs.json').exists())
                if fault == 'world':
                    self.assertIn('make -j1 V=s', (base / 'calls').read_text())
