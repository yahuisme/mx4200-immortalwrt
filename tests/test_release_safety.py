"""Exercise the real nine-image stage and own-main publication gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import ROOT, step
from test_dual_publish import INITRAMFS, profile_fixture, official_record

OFFICIAL_DOWNLOAD_BOUNDARY = r'''
# Replace only the downloader; publication verifies the real helper's record.
python3() {
    if [ "${1:-}" = scripts/official_initramfs.py ]; then
        [ "${FAULT:-}" != official-download ] || return 31
        command python3 - "$@" <<'PY'
import hashlib,json,sys
from pathlib import Path
assert sys.argv[1:] == ['scripts/official_initramfs.py', 'firmware/mx4300-homewrk', '--record', 'build-record/official-initramfs.json']
destination=Path(sys.argv[2]); assert destination.is_dir()
assert len(list(Path('firmware/mx4200').glob('*.bin'))) == 4
assert len([p for p in destination.iterdir() if p.suffix in ('.bin', '.ubi')]) == 4
name='immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb'
source=name.replace('immortalwrt-', 'immortalwrt-25.12.2-', 1)
image=destination/name; image.write_bytes(b'fixture image')
Path(sys.argv[4]).write_text(json.dumps(dict(
    version='25.12.2', source_name=source, name=name, target='qualcommax/ipq807x',
    url='https://downloads.immortalwrt.org/releases/25.12.2/targets/qualcommax/ipq807x/'+source,
    group='mx4300-homewrk', size=image.stat().st_size,
    sha256=hashlib.sha256(image.read_bytes()).hexdigest())))
with Path('official-download-calls').open('a') as stream: stream.write('download\n')
PY
    else
        command python3 "$@"
    fi
}
'''



class ReleaseTests(unittest.TestCase):
    def test_official_download_follows_native_stage_and_no_ram_compilation(self):
        body=step('Validate and stage firmware')['run']
        download='python3 scripts/official_initramfs.py firmware/mx4300-homewrk --record build-record/official-initramfs.json'
        self.assertIn(download, body)
        self.assertLess(body.index('python3 scripts/release_images.py stage'), body.index(download))
        from test_cache_workflow import STEPS
        workflow='\n'.join(item.get('run', '') for item in STEPS)
        self.assertNotIn('build_ramboot.sh', workflow)
        self.assertNotIn('check_initramfs.py', workflow)

    def fixture(self, base):
        profile_fixture(base)
        (base/'user/default/config.diff').write_text((ROOT/'user/default/config.diff').read_text())
        output=base/'openwrt_bin/targets/qualcommax/ipq807x'
        output.mkdir(parents=True)
        config=(ROOT/'user/default/config.diff').read_text()
        (base/'.config').write_text(config+'\nCONFIG_MODULE_DEFAULT_fixture-driver=y\nCONFIG_PACKAGE_fixture-driver=m\n')
        (base/'tmp').mkdir()
        (base/'tmp/.packageinfo').write_text('')
        (base/'build-record').mkdir()
        (base/'build-record/source-ref.txt').write_text('master\n')
        (base/'build-record/source-revision.txt').write_text('r123-abcdef\n')
        (base/'build-record/source-sha.txt').write_text('c'*40+'\n')
        data={'target':'qualcommax/ipq807x','version_code':'r123-abcdef', 'profiles': {}}
        for device in ('mx4200v1','mx4200v2','mx4300','homewrk'):
            images = []
            for kind in ('factory','sysupgrade'):
                suffix = 'ubi' if device == 'homewrk' and kind == 'factory' else 'bin'
                image = output/f'immortalwrt-qualcommax-ipq807x-linksys_{device}-squashfs-{kind}.{suffix}'
                image.write_bytes(b'fixture-not-firmware')
                images.append(dict(name=image.name, type=kind, filesystem='squashfs',
                                   size=image.stat().st_size,
                                   sha256=hashlib.sha256(image.read_bytes()).hexdigest()))
            data['profiles']['linksys_'+device] = {'images': images}
        (output/'profiles.json').write_text(json.dumps(data))
        return output,data

    def stage(self,base,fault='none'):
        prefix=OFFICIAL_DOWNLOAD_BOUNDARY+'''
sudo() { "$@"; }
docker_exec() { shift; "$@"; }
'''
        return subprocess.run(['bash','-eo','pipefail','-c',prefix+step('Validate and stage firmware')['run']],
                              cwd=base,env=dict(os.environ,DK_OPENWRT=str(base),DK_BIN=str(base/'openwrt_bin'),FAULT=fault),text=True,capture_output=True)

    def test_official_download_failure_blocks_stage_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); self.fixture(base)
            result = self.stage(base, 'official-download')
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((base/'build-record/official-initramfs.json').exists())
            self.assertFalse((base/'firmware/mx4300-homewrk'/INITRAMFS).exists())
            self.assertFalse(list((base/'firmware').glob('*/version.txt')))
            self.assertFalse(list((base/'firmware').glob('*/title.txt')))

    def test_complete_stage_and_bad_image_configuration_matrix(self):
        cases=('valid','missing','empty','extra','wrong-device','wrong-prefix','symlink',
               'wrong-target','wrong-profile','wrong-version','missing-app','excluded-module','missing-default')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp); out,data=self.fixture(base)
                image=out/'immortalwrt-qualcommax-ipq807x-linksys_mx4200v1-squashfs-factory.bin'
                if case=='missing': image.unlink()
                if case=='empty': image.write_bytes(b'')
                if case=='extra': (out/'other-sysupgrade.bin').write_bytes(b'x')
                if case=='wrong-device': image.rename(out/image.name.replace('mx4200v1','mx9999'))
                if case=='wrong-prefix': image.rename(out/image.name.replace('immortalwrt-','openwrt-'))
                if case=='symlink':
                    image.rename(out/'payload'); image.symlink_to('payload')
                if case=='wrong-target': data['target']='airoha/an7581'
                if case=='wrong-profile': data['profiles']['other']=data['profiles'].pop('linksys_mx4200v1')
                if case=='wrong-version': data['version_code']='SNAPSHOT'
                config=(base/'.config').read_text()
                if case=='missing-app': config=config.replace('CONFIG_PACKAGE_luci-app-ttyd=y','')
                if case=='excluded-module':
                    config += '\nCONFIG_PACKAGE_usteer=m\n'
                    self.assertNotEqual(config, (base/'.config').read_text())
                if case=='missing-default': config=config.replace('CONFIG_PACKAGE_fixture-driver=m','')
                (base/'.config').write_text(config)
                (out/'profiles.json').write_text(json.dumps(data))
                result=self.stage(base)
                self.assertEqual(result.returncode==0,case=='valid',result.stderr)
                if case=='valid':
                    from test_dual_publish import GROUPS
                    profile=json.loads((ROOT/'user/default/build.json').read_text())
                    suffixes=[]
                    for group,device in GROUPS.items():
                        directory=base/'firmware'/group
                        self.assertEqual({p.name for p in directory.iterdir() if p.suffix in ('.bin','.ubi','.itb')},
                                         set(profile['release_groups'][group]['images']))
                        tag=(directory/'version.txt').read_text().strip()
                        title=(directory/'title.txt').read_text().strip()
                        self.assertRegex(tag,rf'^{device}-ImmortalWrt-r123-\d\d\.\d\d\.\d\d_\d\d\.\d\d\.\d\d$')
                        self.assertNotIn('snapshot', title.lower())
                        self.assertEqual(title,tag)
                        suffixes.append(tag.removeprefix(device+'-ImmortalWrt-'))
                        notes=(directory/'release-notes.md').read_text()
                        for text in ('`factory.bin`','`sysupgrade.bin`','构建时间：',
                                     '[ImmortalWrt master](https://github.com/immortalwrt/immortalwrt)',
                                     '请选择对应机型镜像，不可混刷。','[默认设置与使用说明]'):
                            self.assertIn(text,notes)
                        for text in ('UBI2','首次刷机教程','linksys-first-flash.md',
                                     '- 机型：','- 定制：','官方 snapshot','c'*40):
                            self.assertNotIn(text,notes)
                        self.assertEqual(sum(line.startswith('- ') for line in notes.splitlines()),4)
                    self.assertEqual(suffixes[0],suffixes[1])
                    notes=(base/'firmware/mx4300-homewrk/release-notes.md').read_text()
                    self.assertNotIn('`factory.ubi`',notes)
                    self.assertIn('LuCI',notes)
                    self.assertIn('25.12.2',notes)
                    self.assertNotIn(official_record()['url'],notes)
                    self.assertNotIn('initramfs-uImage.itb',notes)
                    self.assertTrue((base/'build-record/official-initramfs.json').is_file())
                    self.assertTrue((base/'firmware/mx4300-homewrk'/INITRAMFS).is_file())
                    self.assertEqual((base/'official-download-calls').read_text().splitlines(), ['download'])
                    self.assertFalse((out/INITRAMFS).exists())
                    self.assertEqual(json.loads((base/'build-record/official-initramfs.json').read_text()), official_record())
                    self.assertNotIn('`factory.ubi`',(base/'firmware/mx4200/release-notes.md').read_text())
                    self.assertNotIn('not found',result.stderr)
                else:
                    self.assertFalse((base/'firmware').exists(),result.stdout+result.stderr)

    def test_new_model_failure_rejects_entire_single_build_before_staging(self):
        for case in ('missing-homewrk-ubi','missing-mx4300-profile','extra-ubi','legacy-only'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp); output,data=self.fixture(base)
                if case=='missing-homewrk-ubi':
                    (output/'immortalwrt-qualcommax-ipq807x-linksys_homewrk-squashfs-factory.ubi').unlink()
                if case=='missing-mx4300-profile': data['profiles'].pop('linksys_mx4300')
                if case=='extra-ubi':
                    elsewhere=base/'openwrt_bin/targets/other'; elsewhere.mkdir()
                    (elsewhere/'unexpected-factory.ubi').write_bytes(b'x')
                if case=='legacy-only':
                    for device in ('mx4300','homewrk'):
                        data['profiles'].pop('linksys_'+device)
                        for path in output.glob('*linksys_'+device+'-*'): path.unlink()
                (output/'profiles.json').write_text(json.dumps(data))
                result=self.stage(base)
                self.assertNotEqual(result.returncode,0,result.stderr)
                self.assertFalse((base/'firmware').exists())

    def test_zero_or_mismatched_metadata_revision_never_gets_release_identity(self):
        for case in ('zero', 'mismatched', 'missing-record'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                output, data = self.fixture(base)
                if case == 'zero':
                    data['version_code'] = 'r0-abcdef'
                    (base / 'build-record/source-revision.txt').write_text('r0-abcdef\n')
                elif case == 'mismatched':
                    (base / 'build-record/source-revision.txt').write_text('r124-abcdef\n')
                else:
                    (base / 'build-record/source-revision.txt').unlink()
                (output / 'profiles.json').write_text(json.dumps(data))
                result = self.stage(base)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(list((base / 'firmware').glob('*/version.txt')))
                self.assertFalse(list((base / 'firmware').glob('*/title.txt')))

    def test_own_main_freshness_before_create_and_prune(self):
        from test_dual_publish import replay, staged_fixture
        cases=('fresh','annotated','stale','error','empty','malformed','advance','recheck-error',
               'create-error','verify-error','title-error','tag-error','tag-ref-error')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp); pages=staged_fixture(base)
                result,calls=replay(base,pages,case)
                gates=[a for a in calls if a[0]=='api' and a[1].endswith('/git/ref/heads/main')]
                creates=[a for a in calls if a[:2]==['release','create']]
                deletes=[a for a in calls if a[:2]==['release','delete']]
                self.assertEqual(result.returncode==0,case in ('fresh','annotated','stale','advance'),result.stderr)
                self.assertEqual(len(creates),2 if case in ('fresh','annotated','advance','recheck-error') else
                                 0 if case in ('stale','error','empty','malformed') else 1)
                self.assertEqual(len(gates),5 if case in ('fresh','annotated') else
                                 4 if case in ('advance','recheck-error') else
                                 1 if case in ('stale','error','empty','malformed') else 2)
                tag_refs=[a for a in calls if a[0]=='api' and '/git/ref/tags/' in a[1]]
                self.assertEqual(len(tag_refs),2 if case in ('fresh','annotated','advance','recheck-error') else
                                 1 if case in ('tag-error','tag-ref-error') else 0)
                self.assertEqual([a[2] for a in deletes],
                                 ['MX4200-ImmortalWrt-old','MX4300-ImmortalWrt-old']
                                 if case in ('fresh','annotated') else [])
                self.assertTrue(all('immortalwrt/immortalwrt' not in ' '.join(a) for a in calls))
