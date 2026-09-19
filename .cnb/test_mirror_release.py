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

    def request(self, url, method='GET', data=None, **kwargs):
        self.calls.append((url, method, data))
        if url == mirror.GITHUB:
            return self.release
        if url.endswith('/latest') or '/tags/' in url:
            raise urllib.error.HTTPError(url, 404, 'missing', None, None)
        if url.startswith('https://github.com/'):
            return self.files[url.rsplit('/', 1)[1]]
        if url == mirror.CNB:
            return {'id': '123'}
        if url.endswith('/asset-upload-url'):
            return {'upload_url': 'https://storage.example/upload',
                    'verify_url': '/507space/FlClash-alpha/-/releases/123/confirm'}
        return None

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


if __name__ == '__main__':
    unittest.main()
