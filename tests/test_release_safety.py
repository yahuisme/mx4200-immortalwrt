"""Exercise the real four-image stage and two own-main publication gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import ROOT, step


class ReleaseTests(unittest.TestCase):
    def fixture(self, base):
        (base/'scripts').symlink_to(ROOT/'scripts')
        (base/'user').symlink_to(ROOT/'user')
        output=base/'openwrt_bin/targets/qualcommax/ipq807x'
        output.mkdir(parents=True)
        config=(ROOT/'user/default/config.diff').read_text()
        (base/'.config').write_text(config+'\nCONFIG_MODULE_DEFAULT_fixture-driver=y\nCONFIG_PACKAGE_fixture-driver=m\n')
        (base/'tmp').mkdir()
        (base/'tmp/.packageinfo').write_text('')
        (base/'build-record').mkdir()
        (base/'build-record/source-tag.txt').write_text('v25.12.2\n')
        for device in ('mx4200v1','mx4200v2'):
            for kind in ('factory','sysupgrade'):
                (output/f'immortalwrt-qualcommax-ipq807x-linksys_{device}-squashfs-{kind}.bin').write_bytes(b'fixture-not-firmware')
        data={'target':'qualcommax/ipq807x','version_code':'r123-abcdef',
              'profiles':{'linksys_mx4200v1':{},'linksys_mx4200v2':{}}}
        (output/'profiles.json').write_text(json.dumps(data))
        return output,data

    def stage(self,base):
        prefix='sudo() { "$@"; }; docker_exec() { shift; "$@"; };\n'
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
                if case=='missing-app': config=config.replace('CONFIG_PACKAGE_luci-app-homeproxy=y','')
                if case=='excluded-module':
                    config += '\nCONFIG_PACKAGE_usteer=m\n'
                    self.assertNotEqual(config, (base/'.config').read_text())
                if case=='missing-default': config=config.replace('CONFIG_PACKAGE_fixture-driver=m','')
                (base/'.config').write_text(config)
                (out/'profiles.json').write_text(json.dumps(data))
                result=self.stage(base)
                self.assertEqual(result.returncode==0,case=='valid',result.stderr)
                if case=='valid':
                    self.assertEqual(len(list((base/'firmware').glob('*.bin'))),4)
                    tag=(base/'firmware/version.txt').read_text().strip()
                    title=(base/'firmware/title.txt').read_text().strip()
                    self.assertRegex(tag,r'^MX4200-ImmortalWrt-25\.12\.2-r123-\d\d\.\d\d\.\d\d_\d\d\.\d\d\.\d\d$')
                    self.assertRegex(title,r'^MX4200-ImmortalWrt-25\.12\.2-r123-\d\d\.\d\d\.\d\d_\d\d\.\d\d\.\d\d$')
                    notes=(base/'firmware/release-notes.md').read_text()
                    self.assertIn('`factory.bin`',notes)
                    self.assertIn('`sysupgrade.bin`',notes)
                    self.assertIn('构建时间：',notes)
                    self.assertNotIn('UBI2',notes)
                    self.assertNotIn('not found',result.stderr)
                else:
                    self.assertFalse((base/'firmware').exists(),result.stdout+result.stderr)

    def test_own_main_freshness_before_create_and_prune(self):
        cases=('fresh','stale','error','empty','malformed','advance','recheck-error','create-error','verify-error')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp); self.fixture(base)
                stage=self.stage(base); self.assertEqual(stage.returncode,0,stage.stderr)
                (base/'gh').write_text('''#!/usr/bin/env python3
import os,json,sys,hashlib
from pathlib import Path
a=sys.argv[1:]; root=Path(os.environ['STUB_ROOT']); mode=os.environ['CASE']
with (root/'calls').open('a') as f: f.write(json.dumps(a)+'\\n')
if a[:2]==['api','repos/yahuisme/mx4200-immortalwrt/git/ref/heads/main']:
    second=(root/'checked').exists(); (root/'checked').touch()
    if mode=='error' or (second and mode=='recheck-error'): sys.exit(17)
    if mode=='empty': sys.exit(0)
    if mode=='malformed': print('null'); sys.exit(0)
    print('b'*40 if mode=='stale' or (second and mode=='advance') else os.environ['GITHUB_SHA'])
elif a[:2]==['release','create']:
    if mode=='create-error': sys.exit(19)
elif a[0]=='api' and '/releases/tags/' in a[1]:
    if mode=='verify-error': sys.exit(23)
    assets=[dict(name=p.name,size=p.stat().st_size,state='uploaded',digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()) for p in (root/'firmware').glob('*.bin')]
    print(json.dumps(dict(tag_name=(root/'firmware/version.txt').read_text().strip(),draft=False,prerelease=False,assets=assets)))
elif a==['api','--paginate','--slurp','repos/yahuisme/mx4200-immortalwrt/releases?per_page=100']:
    current=(root/'firmware/version.txt').read_text().strip()
    print(json.dumps([[dict(tag_name=t,id=i,published_at=str(i),draft=False,prerelease=False) for i,t in enumerate(['MX4200-ImmortalWrt-old','MX4200-ImmortalWrt-previous',current],1)]]))
elif a[:2]!=['release','delete']: sys.exit(99)
''')
                (base/'gh').chmod(0o755)
                result=subprocess.run(['bash','-eo','pipefail','-c',step('Publish firmware and prune releases')['run']],cwd=base,
                    env=dict(os.environ,PATH=tmp+':'+os.environ['PATH'],STUB_ROOT=tmp,CASE=case,GITHUB_SHA='a'*40,GITHUB_REPOSITORY='yahuisme/mx4200-immortalwrt'),text=True,capture_output=True)
                calls=[json.loads(x) for x in (base/'calls').read_text().splitlines()]
                gates=[a for a in calls if a[:2]==['api','repos/yahuisme/mx4200-immortalwrt/git/ref/heads/main']]
                creates=[a for a in calls if a[:2]==['release','create']]
                deletes=[a for a in calls if a[:2]==['release','delete']]
                self.assertEqual(result.returncode==0,case in ('fresh','stale','advance'),result.stderr)
                self.assertEqual(bool(creates),case in ('fresh','advance','recheck-error','create-error','verify-error'))
                self.assertEqual(len(gates),2 if case in ('fresh','advance','recheck-error') else 1)
                self.assertEqual([a[2] for a in deletes],['MX4200-ImmortalWrt-old'] if case=='fresh' else [])
                if creates:
                    self.assertEqual(creates[0][creates[0].index('--target')+1],'a'*40)
                self.assertTrue(all('immortalwrt/immortalwrt' not in ' '.join(a) for a in calls))
