import hashlib
import importlib.util
import json
import os
import pathlib
import unittest
import urllib.error
from unittest.mock import patch

with patch.dict(os.environ, {'CNB_TOKEN': 'test-only'}):
    spec = importlib.util.spec_from_file_location('mirror', pathlib.Path(__file__).with_name('mirror-release.py'))
    mirror = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mirror)


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.metadata = dict(build=42, applicationId='com.follow.clash.dev',
                             apk=mirror.APK, certificateSha256=mirror.CERT,
                             tag='alpha-42', sha256=hashlib.sha256(b'apk').hexdigest())
        self.release = dict(tag_name='alpha-42', target_commitish='abc', name='Release',
                            draft=False, prerelease=False,
                            body='<!-- flclash-update ' + json.dumps(self.metadata) + ' -->',
                            assets=[dict(name=n, browser_download_url=
                                f'https://github.com/initH271/FlClash-alpha/releases/download/alpha-42/{n}')
                                for n in (mirror.APK, 'update.json', 'SHA256SUMS.txt')])
        self.files = {mirror.APK: b'apk', 'update.json': json.dumps(self.metadata).encode(),
                      'SHA256SUMS.txt': (self.metadata['sha256'] + '  ' + mirror.APK).encode()}

        self.cnb = None
        self.newer_on_cnb = False

    def add_windows(self, setup=b'setup', archive=b'archive'):
        """Give the GitHub release what windows_release.py adds."""
        self.published = {mirror.WINDOWS[0]: setup, mirror.WINDOWS[1]: archive}
        self.files.update(self.published)
        self.files['SHA256SUMS.txt'] += b''.join(
            f'\n{hashlib.sha256(data).hexdigest()}  {name}'.encode() for name, data in self.published.items())
        self.release['assets'] += [dict(name=n, browser_download_url=
            f'https://github.com/initH271/FlClash-alpha/releases/download/alpha-42/{n}') for n in self.published]
        self.resize()

    def resize(self):
        for asset in self.release['assets']:
            asset['size'] = len(self.files[asset['name']])

    def publish_on_cnb(self, *names):
        self.cnb = dict(id='123', draft=False, body=self.release['body'],
                        assets=[dict(name=n, size=len(self.files[n])) for n in names])

    def request(self, url, method='GET', data=None, **kwargs):
        self.calls.append((url, method, data))
        if url == mirror.GITHUB:
            return self.release
        if url.endswith('/latest'):
            if self.newer_on_cnb:
                return {'body': '<!-- flclash-update ' + json.dumps({'build': 43}) + ' -->'}
            raise urllib.error.HTTPError(url, 404, 'missing', None, None)
        if '/tags/' in url:
            if self.cnb is None:
                raise urllib.error.HTTPError(url, 404, 'missing', None, None)
            return self.cnb
        if url.startswith('https://github.com/'):
            return self.files[url.rsplit('/', 1)[1]]
        if url == mirror.CNB:
            self.cnb = dict(id='123', draft=True, body=self.release['body'], assets=[])
            return self.cnb
        if url.endswith('/asset-upload-url'):
            self.uploading = (data['asset_name'], data['size'])
            return {'upload_url': 'https://storage.example/upload',
                    'verify_url': '/507space/FlClash-alpha/-/releases/123/confirm'}
        if url.endswith('/confirm?ttl=0'):
            self.cnb['assets'] = [a for a in self.cnb['assets'] if a['name'] != self.uploading[0]]
            self.cnb['assets'].append(dict(name=self.uploading[0], size=self.uploading[1]))
        if method == 'PATCH':
            self.cnb['draft'] = False
        return None

    def uploaded(self):
        return [c[2]['asset_name'] for c in self.calls if c[0].endswith('/asset-upload-url')]

    def run_mirror(self):
        with patch.object(mirror, 'request', self.request):
            mirror.main()

    def test_draft_is_published_only_after_all_uploads(self):
        with patch.object(mirror, 'request', self.request):
            mirror.main()
        creation = next(c for c in self.calls if c[0] == mirror.CNB)
        self.assertTrue(creation[2]['draft'])
        self.assertEqual(3, sum(c[1] == 'PUT' for c in self.calls))
        self.assertEqual('PATCH', self.calls[-1][1])
        self.assertFalse(self.calls[-1][2]['draft'])

    def test_corrupt_apk_never_creates_release(self):
        self.files[mirror.APK] = b'corrupt'
        with patch.object(mirror, 'request', self.request), self.assertRaises(ValueError):
            mirror.main()
        self.assertFalse(any(c[1] == 'POST' for c in self.calls))

    def test_wrong_signing_identity_rejected(self):
        self.release['body'] = self.release['body'].replace(mirror.CERT, 'wrong')
        with patch.object(mirror, 'request', self.request), self.assertRaises(ValueError):
            mirror.main()
        self.assertEqual(1, len(self.calls))

    def test_an_old_release_is_published_exactly_as_before(self):
        self.resize()
        self.run_mirror()
        self.assertEqual([mirror.APK, 'SHA256SUMS.txt', 'update.json'], self.uploaded())
        self.assertEqual('PATCH', self.calls[-1][1])

    def test_an_old_release_already_on_cnb_uploads_nothing(self):
        self.resize()
        self.publish_on_cnb(mirror.APK, 'SHA256SUMS.txt', 'update.json')
        self.run_mirror()
        self.assertEqual([], self.uploaded())

    def test_a_new_release_carries_windows_after_the_apk_is_published(self):
        self.add_windows()
        self.run_mirror()
        published = self.calls.index(next(c for c in self.calls if c[1] == 'PATCH'))
        names = [c[2]['asset_name'] for c in self.calls[published:] if c[0].endswith('/asset-upload-url')]
        self.assertEqual([*mirror.WINDOWS, 'SHA256SUMS.txt'], names)
        self.assertEqual({mirror.APK, 'SHA256SUMS.txt', 'update.json', *mirror.WINDOWS},
                         {a['name'] for a in self.cnb['assets']})

    def test_a_tag_already_published_gets_the_windows_files_and_new_checksums(self):
        self.resize()
        self.publish_on_cnb(mirror.APK, 'SHA256SUMS.txt', 'update.json')
        self.add_windows()
        self.run_mirror()
        self.assertEqual([*mirror.WINDOWS, 'SHA256SUMS.txt'], self.uploaded())
        self.assertFalse(any(c[1] == 'PATCH' for c in self.calls))

    def test_a_fully_mirrored_release_is_not_uploaded_again(self):
        self.add_windows()
        self.publish_on_cnb(mirror.APK, 'SHA256SUMS.txt', 'update.json', *mirror.WINDOWS)
        self.run_mirror()
        self.assertEqual([], self.uploaded())
        self.assertFalse(any(c[0].startswith('https://github.com/') for c in self.calls))

    def test_checksums_left_behind_by_a_failed_run_catch_up(self):
        self.resize()
        self.publish_on_cnb('SHA256SUMS.txt')
        self.add_windows()
        self.cnb['assets'] += [dict(name=n, size=len(self.files[n])) for n in mirror.WINDOWS]
        self.run_mirror()
        self.assertEqual(['SHA256SUMS.txt'], self.uploaded())

    def test_a_windows_mismatch_uploads_nothing_of_it_and_keeps_the_published_apk(self):
        self.add_windows()
        self.files[mirror.WINDOWS[0]] = b'tampered'
        self.resize()
        with self.assertRaises(ValueError):
            self.run_mirror()
        self.assertEqual([mirror.APK, 'SHA256SUMS.txt', 'update.json'], self.uploaded())
        self.assertFalse(self.cnb['draft'])

    def test_files_without_their_checksum_lines_wait(self):
        self.add_windows()
        self.files['SHA256SUMS.txt'] = (self.metadata['sha256'] + '  ' + mirror.APK).encode()
        self.resize()
        self.publish_on_cnb(mirror.APK, 'SHA256SUMS.txt', 'update.json')
        self.run_mirror()
        self.assertEqual([], self.uploaded())

    def test_refusing_to_downgrade_adds_no_windows_files(self):
        self.add_windows()
        self.newer_on_cnb = True
        self.run_mirror()
        self.assertEqual([], self.uploaded())

    def test_the_checksums_keep_the_apk_first(self):
        self.add_windows()
        self.assertEqual(self.metadata['sha256'], self.files['SHA256SUMS.txt'].decode().split()[0])
        self.run_mirror()
        self.assertFalse(self.cnb['draft'])


if __name__ == '__main__':
    unittest.main()
