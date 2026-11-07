"""Official HomeWRK binary provenance, with no firmware compilation."""
from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import official_initramfs as official

DATA = b'official unchanged original bytes'


def record_for(version='27.02.10'):
    source = official.NAME.replace('immortalwrt-', f'immortalwrt-{version}-', 1)
    return {'version': version, 'url': f'{official.RELEASES}{version}/targets/{official.TARGET}/{source}',
            'source_name': source, 'name': official.NAME, 'size': len(DATA),
            'sha256': hashlib.sha256(DATA).hexdigest(), 'target': official.TARGET,
            'group': official.GROUP}


def metadata(version='27.02.10'):
    record = record_for(version)
    profile = {'target': official.TARGET, 'version_number': version,
               'profiles': {'linksys_homewrk': {'images': [{
                   'type': 'kernel', 'filesystem': 'initramfs', 'name': record['source_name'],
                   'size': record['size'], 'sha256': record['sha256'],
               }]}}}
    return record, profile


def pages_for(record, profile, index=None, sums=None):
    base = record['url'].removesuffix(record['source_name'])
    return {official.RELEASES: (index or (
                '<a href="25.12.2/">old</a><a href="26.01.0/">future</a>'
                '<a href="27.02.9/">nine</a><a href="27.02.10/">ten</a>'
                '<a href="99.01.0-rc1/">rc</a><a href="99.99-SNAPSHOT/">snapshot</a>'
                '<a href="99.99.0">file</a><a href="/99.99.0/">absolute</a>'
                '<a href="https://evil/99.99.0/">external</a>')).encode(),
            base + 'profiles.json': json.dumps(profile).encode(),
            base + 'sha256sums': (sums if sums is not None else
                                  f"{record['sha256']} *{record['source_name']}\n").encode()}


class ResolveTests(unittest.TestCase):
    def resolve_pages(self, pages):
        with patch('urllib.request.urlopen', side_effect=lambda url, **kw: io.BytesIO(pages[url])):
            return official.resolve()

    def test_latest_numeric_stable_future_years_not_pinned(self):
        record, profile = metadata()
        self.assertEqual(self.resolve_pages(pages_for(record, profile)), record)

    def test_next_major_with_zero_padded_month_is_valid(self):
        record, profile = metadata('26.01.0')
        self.assertEqual(self.resolve_pages(pages_for(record, profile,
                         index='<a href="25.12.2/">old</a><a href="26.01.0/">new</a>')), record)

    def test_no_stable_directory(self):
        with self.assertRaisesRegex(ValueError, 'stable'):
            self.resolve_pages({official.RELEASES: b'<a href="27.02-SNAPSHOT/">snapshot</a>'
                                b'<a href="27.02.0-rc1/">rc</a>'})

    def test_latest_missing_target_never_falls_back(self):
        requested = []
        def fetch(url, **kwargs):
            requested.append(url)
            if url == official.RELEASES:
                return io.BytesIO(b'<a href="25.12.2/">old</a><a href="27.02.10/">new</a>')
            raise urllib.error.HTTPError(url, 404, 'missing', Message(), None)
        with patch('urllib.request.urlopen', side_effect=fetch), patch('time.sleep'):
            with self.assertRaises(urllib.error.HTTPError):
                official.resolve()
        self.assertEqual(requested, [official.RELEASES,
                         official.RELEASES + '27.02.10/targets/qualcommax/ipq807x/profiles.json'])

    def test_profiles_identity_and_image_metadata_rejected(self):
        mutations = {
            'target': lambda p: p.update(target='other/target'),
            'version': lambda p: p.update(version_number='27.02.9'),
            'missing_homewrk': lambda p: p['profiles'].clear(),
            'type': lambda p: p['profiles']['linksys_homewrk']['images'][0].update(type='sysupgrade'),
            'filesystem': lambda p: p['profiles']['linksys_homewrk']['images'][0].update(filesystem='squashfs'),
            'traversal': lambda p: p['profiles']['linksys_homewrk']['images'][0].update(name='../evil.itb'),
            'wrong_version': lambda p: p['profiles']['linksys_homewrk']['images'][0].update(name=record_for('25.12.2')['source_name']),
            'duplicate': lambda p: p['profiles']['linksys_homewrk']['images'].append(dict(p['profiles']['linksys_homewrk']['images'][0])),
            'size_bool': lambda p: p['profiles']['linksys_homewrk']['images'][0].update(size=True),
            'size_zero': lambda p: p['profiles']['linksys_homewrk']['images'][0].update(size=0),
            'oversize': lambda p: p['profiles']['linksys_homewrk']['images'][0].update(size=official.MAX_IMAGE_SIZE + 1),
            'bad_sha': lambda p: p['profiles']['linksys_homewrk']['images'][0].update(sha256='not-a-hash'),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                record, profile = metadata()
                mutate(profile)
                with self.assertRaises(ValueError):
                    self.resolve_pages(pages_for(record, profile))

    def test_sha256sums_missing_mismatch_duplicate_rejected(self):
        record, profile = metadata()
        for sums in ('', f"{'0' * 64} *{record['source_name']}\n",
                     (f"{record['sha256']} *{record['source_name']}\n") * 2):
            with self.subTest(sums=sums), self.assertRaisesRegex(ValueError, 'sha256sums'):
                self.resolve_pages(pages_for(record, profile, sums=sums))

    def test_text_mode_sha256sums_accepted(self):
        record, profile = metadata()
        self.assertEqual(self.resolve_pages(pages_for(record, profile,
                         sums=f"{record['sha256']}  {record['source_name']}\n")), record)


class DownloadTests(unittest.TestCase):
    def test_original_bytes_record_and_offline_verify(self):
        record = record_for()
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'images'
            record_path = Path(directory) / 'build-record/official-initramfs.json'
            with patch.object(official, 'resolve', return_value=record), \
                    patch('urllib.request.urlopen', return_value=io.BytesIO(DATA)):
                self.assertEqual(official.download(dest, record_path), record)
            self.assertEqual((dest / official.NAME).read_bytes(), DATA)
            self.assertEqual(official.load_record(record_path), record)
            with patch.object(official, 'resolve', side_effect=AssertionError('must not re-resolve')), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('must stay offline')):
                self.assertEqual(official.verify(dest / official.NAME, record), record)
            (dest / official.NAME).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'size|SHA'):
                official.verify(dest / official.NAME, record)

    def test_bad_download_preserves_existing_bytes_and_record_without_retry(self):
        for label, data in [('hash', b'X' * len(DATA)), ('short', DATA[:-1]),
                            ('oversized', DATA + b'X')]:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                dest = Path(directory)
                image, record_path = dest / official.NAME, dest / 'record.json'
                image.write_bytes(b'previous original image')
                record_path.write_text('previous record')
                with patch.object(official, 'resolve', return_value=record_for()), \
                        patch('urllib.request.urlopen', return_value=io.BytesIO(data)) as request:
                    with self.assertRaises(ValueError):
                        official.download(dest, record_path)
                    self.assertEqual(request.call_count, 1)
                self.assertEqual(image.read_bytes(), b'previous original image')
                self.assertEqual(record_path.read_text(), 'previous record')
                self.assertEqual({p.name for p in dest.iterdir()}, {official.NAME, 'record.json'})

    def test_transient_image_failure_retries_same_resolved_record(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(official, 'resolve', return_value=record_for()) as resolve, \
                patch('urllib.request.urlopen', side_effect=[urllib.error.URLError('offline'),
                      io.BytesIO(DATA)]) as request, patch('time.sleep'):
            official.download(directory, Path(directory) / 'record.json')
            self.assertEqual(resolve.call_count, 1)
            self.assertEqual([call.args[0] for call in request.call_args_list],
                             [record_for()['url']] * 2)

    def test_content_length_mismatch_rejected_before_read(self):
        response = io.BytesIO(DATA)
        response.headers = {'Content-Length': str(len(DATA) + 1)}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(official, 'resolve', return_value=record_for()), \
                patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'Content-Length'):
                official.download(directory, Path(directory) / 'record.json')
            self.assertFalse((Path(directory) / official.NAME).exists())

    def test_verify_rejects_same_size_corruption_symlink_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / official.NAME
            image.write_bytes(b'X' * len(DATA))
            with self.assertRaisesRegex(ValueError, 'SHA'):
                official.verify(image, record_for())
            image.unlink()
            real = Path(directory) / 'real.itb'
            real.write_bytes(DATA)
            image.symlink_to(real)
            with self.assertRaisesRegex(ValueError, 'regular'):
                official.verify(image, record_for())
            with self.assertRaisesRegex(ValueError, 'regular'):
                official.verify(directory, record_for())

    def test_load_record_rejects_invalid_identity(self):
        mutations = {'version': '27.02-SNAPSHOT', 'name': '../evil', 'source_name': '../evil',
                     'url': 'https://evil/image.itb', 'target': 'other/target', 'group': 'mx4200',
                     'size': True, 'sha256': 'bad'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            for key, value in mutations.items():
                with self.subTest(key=key):
                    path.write_text(json.dumps(dict(record_for(), **{key: value})))
                    with self.assertRaises(ValueError):
                        official.load_record(path)

    def test_load_record_rejects_symlink_directory_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps(record_for()))
            link = Path(directory) / 'link.json'
            link.symlink_to(path)
            for invalid in (link, Path(directory)):
                with self.subTest(path=invalid), self.assertRaises(ValueError):
                    official.load_record(invalid)
            path.write_text('')
            with self.assertRaises(ValueError):
                official.load_record(path)

    def test_download_rejects_record_aliases_image(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            image = dest / official.NAME
            image.write_bytes(DATA)
            for record_path in (image, dest / 'link.json', dest / 'hardlink.json'):
                if record_path.name == 'link.json':
                    record_path.symlink_to(image)
                elif record_path.name == 'hardlink.json':
                    record_path.hardlink_to(image)
                with self.subTest(record_path=record_path), \
                        patch.object(official, 'resolve', return_value=record_for()), \
                        patch('urllib.request.urlopen', side_effect=AssertionError('must reject before network')):
                    with self.assertRaises(ValueError):
                        official.download(dest, record_path)
                self.assertEqual(image.read_bytes(), DATA)

    def test_direct_destination_cli_download(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, 'argv', ['official_initramfs.py', directory, '--record',
                                          str(Path(directory) / 'record.json')]), \
                patch.object(official, 'resolve', return_value=record_for()), \
                patch('urllib.request.urlopen', return_value=io.BytesIO(DATA)), patch('builtins.print'):
            official.main()
            self.assertEqual((Path(directory) / official.NAME).read_bytes(), DATA)

    def test_verify_cli_uses_record_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / official.NAME
            image.write_bytes(DATA)
            record = Path(directory) / 'record.json'
            record.write_text(json.dumps(record_for()))
            result = subprocess.run([sys.executable, str(official.__file__), str(image), '--verify',
                                     '--record', str(record)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), record_for())


class RetryTests(unittest.TestCase):
    def test_metadata_transient_failures_bounded_and_404_not_retried(self):
        with patch('urllib.request.urlopen', side_effect=[urllib.error.URLError('offline'),
                   io.BytesIO(b'ok')]) as request, patch('time.sleep'):
            self.assertEqual(official._metadata(official.RELEASES), 'ok')
            self.assertEqual(request.call_count, 2)
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('offline')) as request, \
                patch('time.sleep'):
            with self.assertRaises(urllib.error.URLError):
                official._metadata(official.RELEASES)
            self.assertEqual(request.call_count, 3)
        error = urllib.error.HTTPError(official.RELEASES, 404, 'missing', Message(), None)
        with patch('urllib.request.urlopen', side_effect=error) as request, patch('time.sleep'):
            with self.assertRaises(urllib.error.HTTPError):
                official._metadata(official.RELEASES)
            self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
