import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

from control import CNB, POLICY, ROOT, api, git, sync_branch


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            redirected.remove_header('Authorization')
        return redirected


def transfer(url, data=None, authenticated=False):
    headers = {'User-Agent': 'FlClash-alpha-fallback'}
    if authenticated:
        if urllib.parse.urlsplit(url).netloc != 'api.cnb.cool':
            raise ValueError('Unexpected authenticated download host')
        headers['Authorization'] = 'Bearer ' + os.environ['CNB_AUTOMATION_TOKEN']
    if data is not None:
        headers['Content-Type'] = 'application/octet-stream'
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method='PUT' if data is not None else 'GET')
    with urllib.request.build_opener(SafeRedirect()).open(req, timeout=180) as response:
        return response.read()


def produce():
    sha = git('rev-parse', 'HEAD')
    if sha != os.environ['EXPECTED_SOURCE_SHA']:
        raise ValueError('Source checkout differs from dispatched commit')
    apk = ROOT / 'build/app/outputs/flutter-apk/app-release.apk'
    metadata = json.loads((ROOT / '.github/release.json').read_text())
    data = apk.read_bytes()
    proof = {'sha': sha, 'build': metadata['build'], 'sha256': hashlib.sha256(data).hexdigest()}
    tag = 'candidate-' + sha
    release = api(f'{CNB}/releases/tags/{tag}', missing=True)
    if release is None:
        release = api(f'{CNB}/releases', 'POST', {'tag_name': tag, 'target_commitish': sha,
            'draft': True, 'name': 'Temporary unsigned build ' + sha[:12], 'body': json.dumps(proof)})
    if not release['draft']:
        raise ValueError('Temporary build must remain private/draft')
    for name, payload in {'unsigned.apk': data, 'build.json': json.dumps(proof).encode()}.items():
        upload = api(f'{CNB}/releases/{release["id"]}/asset-upload-url', 'POST',
                     {'asset_name': name, 'size': len(payload), 'overwrite': True, 'ttl': 1})
        transfer(upload['upload_url'], payload)
        verify = urllib.parse.urljoin('https://api.cnb.cool', upload['verify_url'])
        api(verify + ('&' if '?' in verify else '?') + 'ttl=1', 'POST')
    api(f'{CNB}/releases/{release["id"]}', 'PATCH', {'body': json.dumps(proof)})
    print('Uploaded temporary unsigned artifact; no release published')


def remaining_hours():
    group = POLICY['cnb'].split('/')[0]
    quota = api(f'https://api.cnb.cool/{group}/-/charge/quota')
    used = api(f'https://api.cnb.cool/{group}/-/charge/volume')
    return max(0, (quota['ci_in_sec']['free'] - used['ci_in_sec']) / 3600)


def consume():
    if remaining_hours() < POLICY['fallback_min_core_hours']:
        raise ValueError('Insufficient free CNB quota for bounded fallback')
    sha = git('rev-parse', 'HEAD')
    branch = 'automation/build-' + sha
    sync_branch(branch)
    started = api(f'{CNB}/build/start', 'POST', {'sha': sha, 'branch': branch,
        'event': 'api_trigger_fallback', 'sync': 'false',
        'env': {'EXPECTED_SOURCE_SHA': sha}, 'title': f'Fallback Android {sha[:12]}'})
    sn = started['sn']
    completed = False
    try:
        deadline = time.monotonic() + 50 * 60
        while time.monotonic() < deadline:
            state = api(f'{CNB}/build/status/{sn}')['status']
            if state == 'success':
                completed = True
                break
            if state in ('error', 'cancel', 'failed'):
                completed = True
                raise ValueError(f'CNB fallback ended with {state}; inspect build {sn}')
            time.sleep(30)
        if not completed:
            raise TimeoutError('CNB fallback exceeded 50 minutes')
    finally:
        if not completed:
            api(f'{CNB}/build/stop/{sn}', 'POST')
    release = api(f'{CNB}/releases/tags/candidate-{sha}')
    if not release['draft']:
        raise ValueError('Unexpected public temporary artifact')
    proof = json.loads(release['body'])
    metadata = json.loads((ROOT / '.github/release.json').read_text())
    if proof['sha'] != sha or proof['build'] != metadata['build']:
        raise ValueError('CNB artifact source/version mismatch')
    url = f'{CNB}/releases/download/candidate-{sha}/unsigned.apk'
    data = transfer(url, authenticated=True)
    if hashlib.sha256(data).hexdigest() != proof['sha256']:
        raise ValueError('CNB artifact checksum mismatch')
    destination = ROOT / 'build/app/outputs/flutter-apk/app-release.apk'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(f'Reused CNB build {sn}; personal signing happens next on GitHub')


if __name__ == '__main__':
    {'produce': produce, 'consume': consume}[sys.argv[1]]()
