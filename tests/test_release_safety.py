"""Exercise the real eight-image stage and own-main publication gates."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import ROOT, step
from test_dual_publish import profile_fixture

OFFICIAL_BOUNDARY = '''
python3() {
    if [ "${1:-}" = scripts/official_initramfs.py ]; then
        [ "${FAULT:-}" != initramfs ] || return 31
        command python3 - "$2" <<'PY'
import json,sys
from pathlib import Path
from scripts.official_initramfs import load_config, verify
config=load_config()
destination=Path(sys.argv[1])/config['name']
destination.write_bytes(b'fixture image')
verify(destination)
Path('build-record/official-initramfs.json').write_text(json.dumps(config))
PY
    else
        command python3 "$@"
    fi
}
'''


class ReleaseTests(unittest.TestCase):
    def test_official_image_download_is_part_of_stage_acceptance(self):
        body=step('Validate and stage firmware')['run']
        self.assertIn('python3 scripts/official_initramfs.py firmware/mx4300-homewrk --record build-record/official-initramfs.json', body)

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
        (base/'build-record/source-tag.txt').write_text('v25.12.2\n')
        data={'target':'qualcommax/ipq807x','version_code':'r123-abcdef', 'profiles': {}}
        for device in ('mx4200v1','mx4200v2','mx4300','homewrk'):
            images = []
            for kind in ('factory','sysupgrade'):
                suffix = 'ubi' if device == 'homewrk' and kind == 'factory' else 'bin'
                image = output/f'immortalwrt-qualcommax-ipq807x-linksys_{device}-squashfs-{kind}.{suffix}'
                image.write_bytes(b'fixture-not-firmware')
                images.append(dict(name=image.name, type=kind, filesystem='squashfs', size=image.stat().st_size))
            data['profiles']['linksys_'+device] = {'images': images}
        (output/'profiles.json').write_text(json.dumps(data))
        return output,data

    def stage(self,base):
        prefix='sudo() { "$@"; }; docker_exec() { shift; "$@"; };\n'+OFFICIAL_BOUNDARY
        return subprocess.run(['bash','-eo','pipefail','-c',prefix+step('Validate and stage firmware')['run']],
                              cwd=base,env=dict(os.environ,DK_OPENWRT=str(base)),text=True,capture_output=True)

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
                        self.assertEqual({p.name for p in directory.iterdir() if p.suffix in ('.bin','.ubi')},
                                         set(profile['release_groups'][group]['images']))
                        tag=(directory/'version.txt').read_text().strip()
                        title=(directory/'title.txt').read_text().strip()
                        self.assertRegex(tag,rf'^{device}-ImmortalWrt-25\.12\.2-r123-\d\d\.\d\d\.\d\d_\d\d\.\d\d\.\d\d$')
                        self.assertEqual(title,tag)
                        suffixes.append(tag.removeprefix(device+'-ImmortalWrt-'))
                        notes=(directory/'release-notes.md').read_text()
                        for text in ('`factory.bin`','`sysupgrade.bin`','构建时间：','HomeProxy','不可混刷'):
                            self.assertIn(text,notes)
                        self.assertNotIn('UBI2',notes)
                    self.assertEqual(suffixes[0],suffixes[1])
                    notes=(base/'firmware/mx4300-homewrk/release-notes.md').read_text()
                    self.assertIn('`factory.ubi`',notes)
                    self.assertIn('LuCI',notes)
                    self.assertIn('25.12.2',notes)
                    self.assertIn('initramfs-uImage.itb',notes)
                    self.assertTrue((base/'build-record/official-initramfs.json').is_file())
                    config=json.loads((base/'user/default/official-initramfs.json').read_text())
                    self.assertTrue((base/'firmware/mx4300-homewrk'/config['name']).is_file())
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
                                 ['MX4200-ImmortalWrt-old','MX4300-HomeWRK-ImmortalWrt-old']
                                 if case in ('fresh','annotated') else [])
                self.assertTrue(all('immortalwrt/immortalwrt' not in ' '.join(a) for a in calls))
