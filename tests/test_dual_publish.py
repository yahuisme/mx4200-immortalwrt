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

GROUPS = {'mx4200': 'MX4200', 'mx4300-homewrk': 'MX4300-HomeWRK'}
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
    second = a[2].startswith('MX4300-HomeWRK-')
    sys.exit(19 if mode == 'create-error' or (second and mode == 'second-create-error') else 0)
if a[0] == 'api' and '/releases/tags/' in a[1]:
    tag = unquote(a[1].split('/releases/tags/')[1])
    group = 'mx4300-homewrk' if tag.startswith('MX4300-HomeWRK-') else 'mx4200'
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
    # Publication compares RAM-image bytes with the checker's build record.
    # Capture this before any negative mutation, so equal-size damage is visible.
    record = base/'build-record'
    record.mkdir()
    (record/'source-sha.txt').write_text('c' * 40 + '\n')
    (record/'source-revision.txt').write_text('r123-abcdef\n')
    (record/'ramboot.json').write_text(json.dumps(dict(
        pristine=True, source_sha='c' * 40, revision='r123-abcdef',
        customization='Chinese LuCI only')))
    (record/'initramfs.json').write_text(json.dumps(dict(
        name=INITRAMFS, size=len(b'fixture image'), complete_cpio=True,
        official_source='c' * 40, language='zh_cn', default_language='auto',
        official_defaults={'etc/config/network': hashlib.sha256(b'official fixture defaults').hexdigest()},
        sha256=hashlib.sha256(b'fixture image').hexdigest())))

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
    def test_native_initramfs_failure_blocks_both_publications(self):
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
                    self.assertIn('digest mismatch', result.stderr)

    def test_initramfs_evidence_failure_blocks_both_publications(self):
        for fault in ('missing', 'malformed', 'incomplete-cpio', 'wrong-name', 'wrong-size', 'wrong-digest'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp); pages = staged_fixture(base)
                evidence = base/'build-record/initramfs.json'
                data = json.loads(evidence.read_text())
                if fault == 'incomplete-cpio': data['complete_cpio'] = False
                if fault == 'wrong-name': data['name'] = 'other.itb'
                if fault == 'wrong-size': data['size'] += 1
                if fault == 'wrong-digest': data['sha256'] = '0'*64
                evidence.write_text('{' if fault == 'malformed' else json.dumps(data))
                if fault == 'missing': evidence.unlink()
                result, calls = replay(base, pages)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(a[0] == 'release' for a in calls))
                self.assertNotIn('ModuleNotFoundError', result.stderr)

    def test_real_checker_record_satisfies_publication_boundary(self):
        from test_ramboot_defaults import source_fixture
        from test_initramfs import checker, payload
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); pages = staged_fixture(base)
            source = base / 'official-source'
            source.mkdir()
            files = source_fixture(source)
            image = base / 'firmware/mx4300-homewrk' / INITRAMFS
            image.write_bytes(payload(files))
            proof = checker.verify(image, base / 'build-record/initramfs.json', source)
            self.assertEqual(proof['default_language'], 'auto')
            self.assertEqual(proof['language'], 'zh_cn')
            (base / 'build-record/source-sha.txt').write_text(proof['official_source'] + '\n')
            ram = json.loads((base / 'build-record/ramboot.json').read_text())
            ram['source_sha'] = proof['official_source']
            (base / 'build-record/ramboot.json').write_text(json.dumps(ram))
            result, calls = replay(base, pages)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len([a for a in calls if a[:2] == ['release', 'create']]), 2)

    def test_original_default_proof_failure_blocks_all_release_mutations(self):
        for fault in ('missing-initramfs-source', 'wrong-initramfs-source', 'missing-language',
                      'wrong-language', 'missing-defaults', 'empty-defaults',
                      'malformed-defaults', 'missing-ramboot', 'malformed-ramboot',
                      'dirty', 'truthy-pristine', 'missing-pristine', 'wrong-source',
                      'wrong-revision', 'missing-source-record', 'missing-revision-record'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                base = Path(directory); pages = staged_fixture(base)
                record = base / 'build-record'
                evidence = json.loads((record / 'initramfs.json').read_text())
                ram = json.loads((record / 'ramboot.json').read_text())
                if fault == 'missing-initramfs-source': evidence.pop('official_source')
                if fault == 'wrong-initramfs-source': evidence['official_source'] = 'd' * 40
                if fault == 'missing-language': evidence.pop('language')
                if fault == 'wrong-language': evidence['language'] = 'auto'
                if fault == 'missing-defaults': evidence.pop('official_defaults')
                if fault == 'empty-defaults': evidence['official_defaults'] = {}
                if fault == 'malformed-defaults': evidence['official_defaults'] = ['not-a-dict']
                if fault == 'dirty': ram['pristine'] = False
                if fault == 'truthy-pristine': ram['pristine'] = 'true'
                if fault == 'missing-pristine': ram.pop('pristine')
                if fault == 'wrong-source': ram['source_sha'] = 'd' * 40
                if fault == 'wrong-revision': ram['revision'] = 'r124-abcdef'
                (record / 'initramfs.json').write_text(json.dumps(evidence))
                (record / 'ramboot.json').write_text('{' if fault == 'malformed-ramboot' else json.dumps(ram))
                if fault == 'missing-ramboot': (record / 'ramboot.json').unlink()
                if fault == 'missing-source-record': (record / 'source-sha.txt').unlink()
                if fault == 'missing-revision-record': (record / 'source-revision.txt').unlink()
                result, calls = replay(base, pages)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(any(call[0] == 'release' for call in calls), calls)
                self.assertNotIn('ModuleNotFoundError', result.stderr)

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
                             ['MX4200-ImmortalWrt-old','MX4300-HomeWRK-ImmortalWrt-old'])

    def test_group_retention_is_disjoint_across_paginated_inventory(self):
        pages = [[row('MX4200-ImmortalWrt-old'), row('MX4300-HomeWRK-ImmortalWrt-old'),
                  row('MX4200_ImmortalWrt_legacy'), row('Other-keep'),
                  row('MX4300-HomeWRK-ImmortalWrt-draft', draft=True)],
                 [row('MX4200-ImmortalWrt-current'), row('MX4300-HomeWRK-ImmortalWrt-current'),
                  row('MX4300-HomeWRK-ImmortalWrt-preview', prerelease=True)]]
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
                             ['MX4300-HomeWRK-ImmortalWrt-old'])

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
        for mode in ('missing','empty','symlink','extra','title','version'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp); pages = staged_fixture(base)
                directory = base/'firmware/mx4300-homewrk'
                image = next(directory.glob('*.ubi'))
                if mode == 'missing': image.unlink()
                if mode == 'empty': image.write_bytes(b'')
                if mode == 'symlink':
                    image.rename(directory/'payload'); image.symlink_to('payload')
                if mode == 'extra': (directory/'extra.bin').write_bytes(b'x')
                if mode == 'title': (directory/'title.txt').write_text('wrong')
                if mode == 'version':
                    for name in ('version.txt','title.txt'):
                        (directory/name).write_text('MX4300-HomeWRK-ImmortalWrt-other')
                result, calls = replay(base, pages)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(a[0] == 'release' for a in calls))
