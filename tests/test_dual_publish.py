"""Replay real dual publication with a local gh boundary; no remote mutations."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_cache_workflow import ROOT, step

GROUPS = {'mx4200': 'MX4200', 'mx4300-homewrk': 'MX4300'}
INITRAMFS = 'immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb'
STUB = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
from pathlib import Path
from urllib.parse import unquote
root = Path(os.environ['STUB_ROOT']); a = sys.argv[1:]; mode = os.environ.get('CASE', 'fresh')
with (root/'calls').open('a') as stream: stream.write(json.dumps(a)+'\n')
if a[0] == 'api' and a[1].endswith('/git/ref/heads/main'):
    count = int((root/'checked').read_text())+1 if (root/'checked').exists() else 1
    (root/'checked').write_text(str(count))
    if mode == 'error' or (count >= 4 and mode == 'recheck-error'): sys.exit(17)
    if mode == 'empty': sys.exit(0)
    if mode == 'malformed': print('null'); sys.exit(0)
    stale = mode == 'stale' or (count >= 4 and mode == 'advance') or (count >= 3 and mode == 'between-groups')
    print('b'*40 if stale else os.environ['GITHUB_SHA']); sys.exit(0)
if a[:2] == ['release', 'create']:
    second = a[2].startswith('MX4300-ImmortalWrt-')
    sys.exit(19 if mode == 'create-error' or (second and mode == 'second-create-error') else 0)
if a[0] == 'api' and '/releases/tags/' in a[1]:
    tag = unquote(a[1].split('/releases/tags/')[1])
    group = 'mx4300-homewrk' if tag.startswith('MX4300-ImmortalWrt-') else 'mx4200'
    if mode == 'verify-error' or (group == 'mx4300-homewrk' and mode == 'second-verify-error'): sys.exit(23)
    directory = root/'firmware'/group
    assets = [dict(id=i, name=p.name, size=p.stat().st_size, state='uploaded',
                   digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest())
              for i,p in enumerate(sorted(p for p in directory.iterdir() if p.suffix in ('.bin','.ubi','.itb')), 1)]
    if mode == 'readback': sys.exit(8)
    if mode == 'bad-json': print('{'); sys.exit(0)
    if mode == 'missing': assets.pop()
    if mode == 'extra': assets.append(dict(name='metadata.json'))
    if mode == 'name': assets[0]['name'] = 'unexpected.bin'
    if mode == 'duplicate': assets[0] = assets[1]
    if mode == 'size': assets[0]['size'] += 1
    if mode == 'state': assets[0]['state'] = 'new'
    if mode == 'digest': assets[0]['digest'] = 'sha256:wrong'
    if mode in ('no-digest', 'download-corrupt', 'download-failed'):
        for asset in assets: asset.pop('digest')
    print(json.dumps(dict(tag_name='wrong' if mode == 'tag' else tag,
                          name='wrong' if mode in ('title','title-error') else tag,
                          target_commitish=os.environ['GITHUB_SHA'], draft=mode == 'draft',
                          prerelease=mode == 'prerelease', assets=assets))); sys.exit(0)
if a[0] == 'api' and '/git/ref/tags/' in a[1]:
    if mode in ('tag-ref','tag-ref-error'): sys.exit(29)
    print(json.dumps(dict(object=dict(type='tag' if mode == 'annotated' else 'commit',
         sha='c'*40 if mode == 'annotated' else 'b'*40 if mode in ('tag-error','tag-sha') else os.environ['GITHUB_SHA'])))); sys.exit(0)
if a[0] == 'api' and '/git/tags/' in a[1]:
    print(json.dumps(dict(object=dict(type='commit',sha=os.environ['GITHUB_SHA'])))); sys.exit(0)
if a[0] == 'api' and '/releases/assets/' in a[1]:
    assert a[2:] == ['-H','Accept: application/octet-stream']
    sys.stdout.buffer.write(b'wrong content' if mode == 'download-corrupt' else b'fixture image')
    sys.exit(8 if mode == 'download-failed' else 0)
if a == ['api','--paginate','--slurp','repos/fixture/repo/releases?per_page=100']:
    print((root/'rows').read_text()); sys.exit(1 if mode == 'list' else 0)
if a[:2] == ['release','delete']:
    assert a[3:] == ['--cleanup-tag','-y']
    sys.exit(1 if mode == 'delete' else 0)
raise SystemExit('unexpected gh invocation: '+repr(a))
'''


def row(tag, **kwargs):
    return dict(tag_name=tag, draft=False, prerelease=False) | kwargs


def profile_fixture(base):
    """Use the production nine-image contract, with harmless local scripts."""
    shutil.copytree(ROOT/'scripts', base/'scripts')
    directory = base/'user/default'
    directory.mkdir(parents=True)
    shutil.copyfile(ROOT/'user/default/build.json', directory/'build.json')



def official_record(data=b'fixture image'):
    """Offline download evidence, not a built or boot-tested firmware image."""
    source_name = INITRAMFS.replace('immortalwrt-', 'immortalwrt-25.12.2-', 1)
    return dict(version='25.12.2',
                url='https://downloads.immortalwrt.org/releases/25.12.2/targets/qualcommax/ipq807x/' + source_name,
                source_name=source_name, name=INITRAMFS, size=len(data),
                sha256=hashlib.sha256(data).hexdigest(), group='mx4300-homewrk',
                target='qualcommax/ipq807x')


def staged_fixture(base):
    """Minimal valid stage tree used only at the publication boundary."""
    profile_fixture(base)
    profile = json.loads((ROOT/'user/default/build.json').read_text())
    rows = []
    for group, device in GROUPS.items():
        directory = base/'firmware'/group
        directory.mkdir(parents=True)
        for name in profile['release_groups'][group]['images']:
            (directory/name).write_bytes(b'fixture image')

        tag = device+'-ImmortalWrt-current'
        (directory/'version.txt').write_text(tag)
        (directory/'title.txt').write_text(tag)
        (directory/'release-notes.md').write_text('fixture notes')
        rows.extend([row(tag), row(device+'-ImmortalWrt-old')])
    # Bind the downloaded official bytes before any equal-size mutation.
    record = base/'build-record'
    record.mkdir()
    (record/'source-sha.txt').write_text('c' * 40 + '\n')
    (record/'source-revision.txt').write_text('r123-abcdef\n')
    (record/'official-initramfs.json').write_text(json.dumps(official_record()))
    images = [dict(name=p.name, size=p.stat().st_size,
                   digest='sha256:' + hashlib.sha256(p.read_bytes()).hexdigest())
              for p in (base/'firmware').glob('*/*') if p.suffix in ('.bin', '.ubi')]
    (record/'build.json').write_text(json.dumps(dict(images=images)))
    metadata = record/'targets/qualcommax/ipq807x/profiles.json'
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps(dict(profiles={
        board: dict(images=[dict(name=row['name'], size=row['size'],
                                 sha256=row['digest'].removeprefix('sha256:'))
                            for row in images if '-' + board + '-' in row['name']])
        for group in profile['release_groups'].values() for board in group['profiles']
    })))

    return [rows]


def replay(base, pages, mode='fresh'):
    (base/'gh').write_text(STUB); (base/'gh').chmod(0o755)
    (base/'rows').write_text(json.dumps(pages))
    result = subprocess.run(['bash','-eo','pipefail','-c',step('Publish firmware and prune releases')['run']],
        cwd=base, env=dict(os.environ, PATH=str(base)+':'+os.environ['PATH'], STUB_ROOT=str(base),
                          CASE=mode, GITHUB_SHA='a'*40, GITHUB_REPOSITORY='fixture/repo'),
        text=True, capture_output=True)
    calls = [json.loads(line) for line in (base/'calls').read_text().splitlines()]
    return result, calls


class DualPublicationTests(unittest.TestCase):
    def test_native_images_are_bound_to_collected_build_record_before_publication(self):
        for fault in ('missing-record', 'malformed-record', 'missing-row', 'duplicate-row',
                      'extra-row', 'wrong-size', 'wrong-digest', 'same-size-corrupt',
                      'second-group-same-size-corrupt'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp); pages = staged_fixture(base)
                path = base/'build-record/build.json'
                record = json.loads(path.read_text())
                if fault == 'missing-row': record['images'].pop()
                if fault == 'duplicate-row': record['images'].append(record['images'][0])
                if fault == 'extra-row': record['images'].append(dict(record['images'][0], name='unexpected.bin'))
                if fault == 'wrong-size': record['images'][0]['size'] += 1
                if fault == 'wrong-digest': record['images'][0]['digest'] = 'sha256:' + '0'*64
                path.write_text('{' if fault == 'malformed-record' else json.dumps(record))
                if fault == 'missing-record': path.unlink()
                if fault.endswith('same-size-corrupt'):
                    group = 'mx4300-homewrk' if fault.startswith('second-group-') else 'mx4200'
                    image = next((base/'firmware'/group).glob('*factory.*'))
                    image.write_bytes(b'x' * image.stat().st_size)
                result, calls = replay(base, pages)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(a[0] == 'release' for a in calls), calls)
                if fault.endswith('same-size-corrupt'):
                    self.assertIn('Staged image differs from build record', result.stderr)

    def test_native_metadata_failures_block_both_publications(self):
        for fault in ('missing', 'malformed', 'missing-row', 'duplicate-row',
                      'wrong-size', 'wrong-digest', 'missing-digest'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                pages = staged_fixture(base)
                path = base/'build-record/targets/qualcommax/ipq807x/profiles.json'
                data = json.loads(path.read_text())
                images = next(iter(data['profiles'].values()))['images']
                if fault == 'missing-row': images.pop()
                if fault == 'duplicate-row': images.append(dict(images[0]))
                if fault == 'wrong-size': images[0]['size'] += 1
                if fault == 'wrong-digest': images[0]['sha256'] = '0' * 64
                if fault == 'missing-digest': images[0].pop('sha256')
                path.write_text('{' if fault == 'malformed' else json.dumps(data))
                if fault == 'missing': path.unlink()
                result, calls = replay(base, pages)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(a[0] == 'release' for a in calls))

    def test_native_metadata_digest_mismatch_blocks_both_publications(self):
        for group in GROUPS:
            with self.subTest(group=group), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                pages = staged_fixture(base)
                image = next((base/'firmware'/group).glob('*factory.*'))
                image.write_bytes(b'x' * image.stat().st_size)
                record = base/'build-record/build.json'
                data = json.loads(record.read_text())
                for row in data['images']:
                    if row['name'] == image.name:
                        row['digest'] = 'sha256:' + hashlib.sha256(image.read_bytes()).hexdigest()
                record.write_text(json.dumps(data))
                result, calls = replay(base, pages)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('Native image differs from profiles metadata', result.stderr)
                self.assertFalse(any(a[0] == 'release' for a in calls))

    def test_official_attachment_failure_blocks_both_publications(self):
        for mode in ('missing', 'empty', 'same-size-corrupt', 'symlink', 'wrong-group'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp); pages = staged_fixture(base)
                image = base/'firmware/mx4300-homewrk'/INITRAMFS
                if mode == 'missing': image.unlink()
                if mode == 'empty': image.write_bytes(b'')
                if mode == 'same-size-corrupt': image.write_bytes(b'x' * image.stat().st_size)
                if mode == 'symlink':
                    image.rename(image.parent/'payload'); image.symlink_to('payload')
                if mode == 'wrong-group': image.rename(base/'firmware/mx4200'/image.name)
                result, calls = replay(base, pages)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(a[0] == 'release' for a in calls))
                if mode == 'same-size-corrupt':
                    self.assertIn('SHA-256 mismatch', result.stderr)

    def test_official_record_failure_blocks_both_publications(self):
        for fault in ('missing', 'malformed', 'wrong-name', 'wrong-size', 'wrong-digest',
                      'wrong-group', 'snapshot', 'wrong-host', 'wrong-source-name'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp); pages = staged_fixture(base)
                evidence = base/'build-record/official-initramfs.json'
                data = json.loads(evidence.read_text())
                if fault == 'wrong-name': data['name'] = 'other.itb'
                if fault == 'wrong-size': data['size'] += 1
                if fault == 'wrong-digest': data['sha256'] = '0'*64
                if fault == 'wrong-group': data['group'] = 'mx4200'
                if fault == 'snapshot': data['version'] = 'SNAPSHOT'
                if fault == 'wrong-host': data['url'] = data['url'].replace('downloads.immortalwrt.org', 'example.invalid')
                if fault == 'wrong-source-name': data['source_name'] = 'wrong.itb'
                evidence.write_text('{' if fault == 'malformed' else json.dumps(data))
                if fault == 'missing': evidence.unlink()
                result, calls = replay(base, pages)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(a[0] == 'release' for a in calls))
                self.assertNotIn('ModuleNotFoundError', result.stderr)

    def test_publication_uses_locked_record_without_resolving_or_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); pages = staged_fixture(base)
            helper = base/'scripts/official_initramfs.py'
            # Fail any download/resolve attempt, including imported urllib calls.
            with helper.open('a') as stream:
                stream.write("\nimport urllib.request\nurllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError('publication attempted network'))\n")
            result, calls = replay(base, pages)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len([a for a in calls if a[:2] == ['release', 'create']]), 2)
            self.assertEqual(json.loads((base/'build-record/official-initramfs.json').read_text()), official_record())

    def test_unexpected_initramfs_rejected_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); pages = staged_fixture(base)
            (base/'firmware/mx4300-homewrk/unexpected.itb').write_bytes(b'wrong model')
            result, calls = replay(base, pages)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertFalse(any(a[0] == 'release' for a in calls))

    def test_exact_group_assets_explicit_latest_and_verify_before_any_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); pages = staged_fixture(base)
            for group in GROUPS:
                (base/'firmware'/group/'build.json').write_text('private metadata')
            result, calls = replay(base, pages)
            self.assertEqual(result.returncode, 0, result.stderr)
            creates = [a for a in calls if a[:2] == ['release','create']]
            self.assertEqual(len(creates), 2)
            profile = json.loads((ROOT/'user/default/build.json').read_text())
            for index, (group, device) in enumerate(GROUPS.items()):
                call = creates[index]
                self.assertEqual(call[2], device+'-ImmortalWrt-current')
                expected = set(profile['release_groups'][group]['images'])

                self.assertEqual({Path(p).name for p in call[3:call.index('--target')]},
                                 expected)
                self.assertEqual(call[call.index('--target')+1], 'a'*40)
                self.assertEqual(call[call.index('--title')+1], call[2])
                self.assertEqual(call[call.index('--notes-file')+1], f'firmware/{group}/release-notes.md')
                self.assertIn('--latest='+('true' if index == 0 else 'false'), call)
                self.assertIn('--draft=false', call); self.assertIn('--prerelease=false', call)
            first_delete = next(i for i,a in enumerate(calls) if a[:2] == ['release','delete'])
            reads = [i for i,a in enumerate(calls) if a[0] == 'api' and '/git/ref/tags/' in a[1]]
            self.assertEqual(len(reads), 2)
            self.assertTrue(all(index < first_delete for index in reads))
            self.assertEqual([a[2] for a in calls if a[:2] == ['release','delete']],
                             ['MX4200-ImmortalWrt-old','MX4300-ImmortalWrt-old'])

    def test_group_retention_is_disjoint_across_paginated_inventory(self):
        pages = [[row('MX4200-ImmortalWrt-old'), row('MX4300-ImmortalWrt-old'),
                  row('MX4200_ImmortalWrt_legacy'), row('Other-keep'),
                  row('MX4300-ImmortalWrt-draft', draft=True)],
                 [row('MX4200-ImmortalWrt-current'), row('MX4300-ImmortalWrt-current'),
                  row('MX4300-ImmortalWrt-preview', prerelease=True)]]
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); staged_fixture(base)
            result,calls=replay(base,pages)
            self.assertEqual(result.returncode,0,result.stderr)
            inventories=[i for i,a in enumerate(calls) if a[:3]==['api','--paginate','--slurp']]
            self.assertEqual(len(inventories),2)
            deletes=[(i,a[2]) for i,a in enumerate(calls) if a[:2]==['release','delete']]
            self.assertEqual([tag for i,tag in deletes if inventories[0]<i<inventories[1]],
                             ['MX4200-ImmortalWrt-old','MX4200_ImmortalWrt_legacy'])
            self.assertEqual([tag for i,tag in deletes if i>inventories[1]],
                             ['MX4300-ImmortalWrt-old'])

    def test_missing_current_inventory_protects_only_its_own_group(self):
        for missing in GROUPS:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp); pages=staged_fixture(base)
                pages[0]=[r for r in pages[0] if r['tag_name']!=GROUPS[missing]+'-ImmortalWrt-current']
                result,calls=replay(base,pages)
                self.assertEqual(result.returncode,0,result.stderr)
                other=next(device for group,device in GROUPS.items() if group!=missing)
                self.assertEqual([a[2] for a in calls if a[:2]==['release','delete']],
                                 [other+'-ImmortalWrt-old'])
                self.assertIn('::warning::Release inventory unavailable for '+missing,result.stdout)

    def test_second_group_failures_protect_both_release_histories(self):
        for mode in ('second-create-error','second-verify-error','between-groups'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp); pages = staged_fixture(base)
                result, calls = replay(base, pages, mode)
                self.assertEqual(result.returncode == 0, mode == 'between-groups', result.stderr)
                self.assertEqual(len([a for a in calls if a[:2] == ['release','create']]),
                                 1 if mode == 'between-groups' else 2)
                self.assertFalse(any(a[:2] == ['release','delete'] for a in calls))

    def test_both_local_sets_preflight_before_any_mutation(self):
        for group, device in GROUPS.items():
            for mode in ('missing','empty','symlink','extra','title','version'):
                with self.subTest(group=group, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp); pages = staged_fixture(base)
                    directory = base/'firmware'/group
                    image = next(directory.glob('*factory.*'))
                    if mode == 'missing': image.unlink()
                    if mode == 'empty': image.write_bytes(b'')
                    if mode == 'symlink':
                        image.rename(directory/'payload'); image.symlink_to('payload')
                    if mode == 'extra': (directory/'extra.bin').write_bytes(b'x')
                    if mode == 'title': (directory/'title.txt').write_text('wrong')
                    if mode == 'version':
                        for name in ('version.txt','title.txt'):
                            (directory/name).write_text(device+'-ImmortalWrt-other')
                    result, calls = replay(base, pages)
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(any(a[0] == 'release' for a in calls))
