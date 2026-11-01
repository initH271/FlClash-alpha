import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

GITHUB = 'https://api.github.com/repos/initH271/FlClash-alpha/releases/latest'
CNB = 'https://api.cnb.cool/507space/FlClash-alpha/-/releases'
TOKEN = os.environ['CNB_TOKEN']
APK = 'FlClash-alpha-arm64-v8a.apk'
CERT = '4cc5094e24f4a4cfde3a37d6c839ae376bd74c50075d8ee6bc73e25682e9afad'
CHECKSUMS = 'SHA256SUMS.txt'
SETUP = 'FlClash-alpha-windows-amd64-setup.exe'
MANIFEST = 'update-windows.json'
WINDOWS = (SETUP, 'FlClash-alpha-windows-amd64.zip', MANIFEST)


def request(url, method='GET', data=None, authenticated=False, binary=False):
    headers = {'User-Agent': 'FlClash-alpha-release', 'Accept': 'application/json'}
    if authenticated:
        if urllib.parse.urlsplit(url).netloc != 'api.cnb.cool':
            raise ValueError('Refusing to send credentials to another host')
        headers['Authorization'] = f'Bearer {TOKEN}'
    if data is not None and not isinstance(data, bytes):
        data = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = response.read()
        return payload if binary else (json.loads(payload) if payload else None)


def download(asset):
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/initH271/FlClash-alpha/releases/download/'):
        raise ValueError('Unexpected GitHub asset origin')
    return request(url, binary=True)


def upload(release_url, name, data):
    upload_target = request(f'{release_url}/asset-upload-url', 'POST', {
        'asset_name': name, 'size': len(data), 'overwrite': True, 'ttl': 0,
    }, authenticated=True)
    request(upload_target['upload_url'], 'PUT', data, binary=True)
    verify_url = urllib.parse.urljoin('https://api.cnb.cool', upload_target['verify_url'])
    separator = '&' if '?' in verify_url else '?'
    request(verify_url + separator + 'ttl=0', 'POST', authenticated=True)


def check_windows_manifest(data, digest, tag):
    """The app verifies the signature. This only stops a manifest that would send it to a file CNB does not have."""
    payload = json.loads(base64.b64decode(json.loads(data)['payload']))
    if payload['sha256'] != digest or payload['tag'] != tag:
        raise ValueError(f'{MANIFEST} does not describe this {SETUP}')


def mirror_windows(release):
    """Add what GitHub has and the published CNB release lacks. It runs after the APK is safely out, so it can only fail itself."""
    assets = {asset['name']: asset for asset in release['assets']}
    if not any(name in assets for name in WINDOWS):
        return
    tag = urllib.parse.quote(release['tag_name'], safe='')
    published = request(f'{CNB}/tags/{tag}', authenticated=True)
    mirrored = {asset['name']: asset['size'] for asset in published['assets']}
    stale = [name for name in (*WINDOWS, CHECKSUMS) if name in assets and mirrored.get(name) != assets[name]['size']]
    if not stale:
        return
    checksums = download(assets[CHECKSUMS]) if CHECKSUMS in assets else b''
    digests = {line.split()[-1]: line.split()[0] for line in checksums.decode().splitlines() if line.strip()}
    # windows_release.py uploads the checksums last, so a gap means it is still at work or left an Issue behind.
    if not all(name in assets and name in digests for name in WINDOWS):
        print('GitHub release has no complete set of Windows files yet')
        return
    manifest = download(assets[MANIFEST])
    if hashlib.sha256(manifest).hexdigest() != digests[MANIFEST]:
        raise ValueError(f'{MANIFEST} checksum mismatch')
    check_windows_manifest(manifest, digests[SETUP], release['tag_name'])
    release_url = f"{CNB}/{published['id']}"
    for name in WINDOWS:
        if name in stale:
            data = manifest if name == MANIFEST else download(assets[name])
            if hashlib.sha256(data).hexdigest() != digests[name]:
                raise ValueError(f'{name} checksum mismatch')
            upload(release_url, name, data)
            print(f'Mirrored {name}: {len(data)} bytes')
    upload(release_url, CHECKSUMS, checksums)


def main():
    try:
        release = request(GITHUB)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print('No GitHub release to mirror yet')
            return
        raise
    marker = re.search(r'<!-- flclash-update (\{[^\r\n]*\}) -->', release['body'])
    if not marker or release['draft'] or release['prerelease']:
        raise ValueError('Not a published FlClash-alpha release')
    metadata = json.loads(marker[1])
    tag = release['tag_name']
    if (metadata['applicationId'] != 'com.follow.clash.dev'
            or metadata['apk'] != APK or metadata['certificateSha256'] != CERT
            or metadata['tag'] != tag):
        raise ValueError('Unexpected release identity')
    try:
        latest = request(f'{CNB}/latest', authenticated=True)
        latest_marker = re.search(r'<!-- flclash-update (\{[^\r\n]*\}) -->', latest['body'])
        if latest_marker and json.loads(latest_marker[1])['build'] > metadata['build']:
            print('CNB already contains a newer build; refusing to downgrade')
            return
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    try:
        existing = request(f'{CNB}/tags/{urllib.parse.quote(tag, safe="")}', authenticated=True)
        if not existing.get('draft'):
            if existing.get('body') != release['body']:
                raise ValueError('Published tag has different metadata; use a new build number')
            print(f'{tag} already published on CNB')
            mirror_windows(release)
            return
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        existing = None
    files = {}
    for name in (APK, CHECKSUMS, 'update.json'):
        files[name] = download(next(a for a in release['assets'] if a['name'] == name))
    if hashlib.sha256(files[APK]).hexdigest() != metadata['sha256']:
        raise ValueError('APK checksum mismatch')
    if json.loads(files['update.json']) != metadata:
        raise ValueError('Release manifest mismatch')
    if files[CHECKSUMS].decode().split()[0] != metadata['sha256']:
        raise ValueError('Checksum file mismatch')
    if existing is None:
        existing = request(CNB, 'POST', {
            'tag_name': tag, 'target_commitish': release['target_commitish'],
            'name': release['name'], 'body': release['body'],
            'draft': True, 'prerelease': False,
        }, authenticated=True)
    release_url = f"{CNB}/{existing['id']}"
    for name, data in files.items():
        upload(release_url, name, data)
    request(release_url, 'PATCH', {'draft': False, 'make_latest': 'true'}, authenticated=True)
    print(f'Published identical APK on CNB: {tag}')
    mirror_windows(release)


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read())
            reason = detail.get('message', detail.get('errmsg', ''))
        except (ValueError, AttributeError):
            reason = ''
        host = urllib.parse.urlsplit(error.url).netloc
        reason = str(reason).replace(TOKEN, '***')[:300]
        raise SystemExit(f'{host} returned HTTP {error.code}: {reason}') from None
