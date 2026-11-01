"""Plan, check and publish the Windows build of a release, from .github/workflows/windows.yaml."""
import base64
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile

from control import GH, OWNER, POLICY, ROOT, api, bot_issues, comment, comment_once, release_identity

SETUP = 'FlClash-alpha-windows-amd64-setup.exe'
ARCHIVE = 'FlClash-alpha-windows-amd64.zip'
MANIFEST = 'update-windows.json'
CHECKSUMS = 'SHA256SUMS.txt'
OUTPUT = 'dist-windows'
APPLICATION_ID = '94491F5A-A742-4DFF-B144-119A92A2FFD1'
# lib/common/app_update.dart holds the other side: windowsManifestSignaturePrefix and updateSigningCertificate.
SIGNATURE_PREFIX = b'FlClash-alpha-windows-update-v1\n'
CLIENT_SOURCE = 'lib/common/app_update.dart'
# Copied unchanged from update.json. The update dialog shows these, and the notes are the same text Android users read.
COPIED_FIELDS = ('tag', 'build', 'displayVersion', 'sourceSha', 'version', 'upstreamVersion', 'revision',
                 'notes', 'notesBaseTag', 'notesBaseSha', 'notesSourceSha')
# The Android debug store format: .github/scripts/sign-apk.sh uses the same alias and password.
KEY_ALIAS = 'androiddebugkey'
KEY_PASSWORD = 'android'
# What a running installation cannot do without, at the paths windows/CMakeLists.txt installs them to.
BUNDLE = ('FlClash.exe', 'FlClashCore.exe', 'FlClashHelperService.exe', 'flutter_windows.dll', 'data/app.so')
SKIP = {'mode': 'skip', 'source': '', 'tag': ''}


def has_windows(release):
    return {SETUP, ARCHIVE, MANIFEST} <= {asset['name'] for asset in release['assets']}


def identity_at(sha):
    content = api(f'{GH}/contents/.github/release.json?ref={sha}')['content']
    return release_identity(json.loads(base64.b64decode(content)))


def release_by_tag(tag, missing=False):
    return api(f'{GH}/releases/tags/' + urllib.parse.quote(tag, safe=''), missing=missing)


def plan_after_android(run):
    """Only the run that just published a release leads to a Windows build, and that run stays the source."""
    sha = run['head_sha']
    if (run['conclusion'] != 'success' or run['head_branch'] != 'main'
            or (run.get('head_repository') or {}).get('full_name') != POLICY['github']
            or run['event'] not in ('push', 'workflow_dispatch')):
        print('Android run is not a successful build of this repository\'s main')
        return SKIP
    tag = identity_at(sha)['tag']
    release = release_by_tag(tag, missing=True)
    # A merge without a version change finds an older release, whose target is another commit.
    if not release or release['draft'] or release['prerelease'] or release['target_commitish'] != sha:
        print(f'{sha} did not publish {tag}')
        return SKIP
    if has_windows(release):
        print(f'{tag} already has its Windows files')
        return SKIP
    return {'mode': 'publish', 'source': sha, 'tag': tag}


def plan_retry(tag, ref):
    """A person asked for this: anything that cannot be done fails the run rather than doing nothing quietly."""
    if ref != 'refs/heads/main':
        raise ValueError('Publishing runs only from main')
    release = release_by_tag(tag)
    sha = release['target_commitish']
    if release['draft'] or release['prerelease'] or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError(f'{tag} is not a published release with an exact source commit')
    if identity_at(sha)['tag'] != tag:
        raise ValueError(f'{sha} does not carry the identity of {tag}')
    if has_windows(release):
        print(f'::notice::{tag} already has its Windows files; nothing to do')
        return SKIP
    return {'mode': 'publish', 'source': sha, 'tag': tag}


def choose_plan(event_name, event, release_tag, ref, sha):
    if event_name == 'workflow_run':
        return plan_after_android(event['workflow_run'])
    if event_name == 'workflow_dispatch' and release_tag:
        return plan_retry(release_tag, ref)
    return {'mode': 'compile', 'source': sha, 'tag': ''}


def plan():
    event = json.loads(pathlib.Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    result = choose_plan(os.environ['GITHUB_EVENT_NAME'], event, os.getenv('RELEASE_TAG', '').strip(),
                         os.environ['GITHUB_REF'], os.environ['GITHUB_SHA'])
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.writelines(f'{key}={value}\n' for key, value in result.items())
    print(result)


def local_identity(root=ROOT):
    return release_identity(json.loads((root / '.github/release.json').read_text(encoding='utf-8')))


def package_version(identity):
    return f'{identity["displayVersion"]}+{identity["build"]}'


def stamp(root=ROOT):
    """flutter_distributor and the Windows runner take the version only from pubspec.yaml, not from --build-name."""
    path = root / 'pubspec.yaml'
    text, count = re.subn(r'^version: .*$', 'version: ' + package_version(local_identity(root)),
                          path.read_text(encoding='utf-8'), count=1, flags=re.M)
    if count != 1:
        raise ValueError('pubspec.yaml has no version line')
    path.write_text(text, encoding='utf-8')


def product_version(data):
    """The ProductVersion string of a PE file, read without running or fully parsing it."""
    key = 'ProductVersion'.encode('utf-16-le') + b'\0\0'
    at = data.rfind(key)
    if at < 0:
        return None
    at += len(key)
    while data[at:at + 2] == b'\0\0':
        at += 2
    end = at
    while data[end:end + 2] != b'\0\0' and end < len(data):
        end += 2
    # Inno Setup pads this string with spaces.
    return data[at:end].decode('utf-16-le').strip()


def verify(directory, identity):
    """Fail before anything is uploaded when a file is missing, incomplete or carries another version."""
    directory = pathlib.Path(directory)
    expected = package_version(identity)
    with zipfile.ZipFile(directory / ARCHIVE) as archive:
        names = set(archive.namelist())
        missing = [name for name in BUNDLE if name not in names]
        if missing:
            raise ValueError(f'{ARCHIVE} lacks {missing}')
        found = product_version(archive.read('FlClash.exe'))
    if found != expected:
        raise ValueError(f'FlClash.exe is version {found}, expected {expected}')
    found = product_version((directory / SETUP).read_bytes())
    if found != expected:
        raise ValueError(f'{SETUP} is version {found}, expected {expected}')


def package(root=ROOT):
    """Give flutter_distributor's versioned names the fixed ones the Release uses, and check the result."""
    out = root / OUTPUT
    out.mkdir(exist_ok=True)
    for pattern, name in (('*-windows-amd64-setup.exe', SETUP), ('*-windows-amd64.zip', ARCHIVE)):
        found = sorted((root / 'dist').glob(pattern))
        if len(found) != 1:
            raise ValueError(f'Expected one {pattern} in dist, found {[path.name for path in found]}')
        shutil.copyfile(found[0], out / name)
        print(f'{name}: {(out / name).stat().st_size} bytes')
    verify(out, local_identity(root))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def merge_checksums(existing, digests):
    """The APK line stays first and unchanged: the CNB mirror and anyone checking by hand read it there."""
    kept = [line for line in existing.splitlines() if line.strip() and line.split()[-1] not in digests]
    if not kept:
        raise ValueError(f'{CHECKSUMS} has no line for the APK')
    return '\n'.join(kept + [f'{digest}  {name}' for name, digest in digests.items()]) + '\n'


def manifest_payload(update, setup, published_at):
    """What the app learns about this release, as bytes that get signed."""
    payload = {field: update[field] for field in COPIED_FIELDS if field in update}
    payload.update(applicationId=APPLICATION_ID, installer=SETUP, sha256=sha256(setup), size=setup.stat().st_size,
                   publishedAt=published_at)
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()


def run_quietly(*command, stdin=None):
    """Keeps tool output, which could quote key material, out of the job log."""
    result = subprocess.run(command, input=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        raise ValueError(f'{command[0]} {command[1]} failed with {result.returncode}')


def private_key(keystore, directory):
    """keytool reads JKS and PKCS12 alike, and openssl only PKCS12, so this does not depend on the store's format."""
    store = directory / 'signing.keystore'
    store.write_bytes(keystore)
    pkcs12, key = directory / 'signing.p12', directory / 'signing.pem'
    run_quietly('keytool', '-importkeystore', '-noprompt', '-srckeystore', str(store), '-srcstorepass', KEY_PASSWORD,
                '-srcalias', KEY_ALIAS, '-srckeypass', KEY_PASSWORD, '-destkeystore', str(pkcs12),
                '-deststoretype', 'PKCS12', '-deststorepass', KEY_PASSWORD, '-destkeypass', KEY_PASSWORD)
    run_quietly('openssl', 'pkcs12', '-in', str(pkcs12), '-passin', f'pass:{KEY_PASSWORD}', '-nocerts', '-nodes',
                '-out', str(key))
    return key


def signature_matches(payload, signature, certificate, directory):
    der, public, signature_file = directory / 'signing.der', directory / 'signing.pub', directory / 'manifest.sig'
    der.write_bytes(certificate)
    signature_file.write_bytes(signature)
    run_quietly('openssl', 'x509', '-inform', 'DER', '-in', str(der), '-pubkey', '-noout', '-out', str(public))
    try:
        run_quietly('openssl', 'dgst', '-sha256', '-verify', str(public), '-signature', str(signature_file),
                    stdin=SIGNATURE_PREFIX + payload)
    except ValueError:
        return False
    return True


def client_certificate(root=ROOT):
    source = (root / CLIENT_SOURCE).read_text(encoding='utf-8')
    literal = re.search(r"updateSigningCertificate =\s*((?:'[^']*'\s*)+);", source)
    if not literal:
        raise ValueError(f'{CLIENT_SOURCE} has no updateSigningCertificate')
    return base64.b64decode(''.join(re.findall(r"'([^']*)'", literal[1])))


def signed_manifest(payload, keystore, certificate):
    """The manifest as served. The key lives only for this call, and what it signed must verify as the app will verify it."""
    encoded = base64.b64encode(payload)
    with tempfile.TemporaryDirectory() as work:
        directory = pathlib.Path(work)
        key = private_key(keystore, directory)
        output = directory / 'manifest.sig'
        run_quietly('openssl', 'dgst', '-sha256', '-sign', str(key), '-out', str(output),
                    stdin=SIGNATURE_PREFIX + encoded)
        signature = output.read_bytes()
        if not signature_matches(encoded, signature, certificate, directory):
            raise ValueError('The signing key does not match the certificate the app carries')
    return json.dumps({'payload': encoded.decode(), 'signature': base64.b64encode(signature).decode()}) + '\n'


def gh(*args):
    return subprocess.run(['gh', *args, '--repo', POLICY['github']], check=True, stdout=subprocess.PIPE).stdout


def issue_title(tag):
    return f'[Windows 构建待处理] {tag}'


def close_report(tag):
    # The files are public by now: an Issue left open is tidied by the next success or by hand.
    try:
        for issue in bot_issues('open'):
            if issue['title'] == issue_title(tag):
                comment(issue['number'], 'Windows 文件已上传到这个 Release，关闭记录。')
                api(f'{GH}/issues/{issue["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})
    except (RuntimeError, KeyError, OSError) as error:
        print(f'Published; Issue cleanup needs a hand: {error}')


def publish(root=ROOT):
    tag, source = os.environ['TAG'], os.environ['SOURCE']
    release = release_by_tag(tag)
    identity = identity_at(source)
    if release['draft'] or release['target_commitish'] != source or identity['tag'] != tag:
        raise ValueError(f'{tag} is not the published release of {source}')
    out = root / OUTPUT
    verify(out, identity)
    update = json.loads(gh('release', 'download', tag, '--pattern', 'update.json', '--output', '-'))
    certificate = client_certificate(root)
    if update['tag'] != tag or update['build'] != identity['build']:
        raise ValueError(f'update.json of {tag} describes {update["tag"]}')
    if hashlib.sha256(certificate).hexdigest() != update['certificateSha256']:
        raise ValueError(f'{CLIENT_SOURCE} carries another certificate than the APK of {tag}')
    manifest = out / MANIFEST
    # Before any upload, so a key that cannot sign leaves the Release as it was.
    manifest.write_text(signed_manifest(manifest_payload(update, out / SETUP, release['published_at']),
                                        base64.b64decode(os.environ['KEYSTORE_BASE64'], validate=True), certificate),
                        encoding='utf-8')
    packages = (out / SETUP, out / ARCHIVE)
    merged = merge_checksums(gh('release', 'download', tag, '--pattern', CHECKSUMS, '--output', '-').decode(),
                             {path.name: sha256(path) for path in (*packages, manifest)})
    checksums = root / CHECKSUMS
    checksums.write_text(merged, encoding='utf-8')
    gh('release', 'upload', tag, *map(str, packages), '--clobber')
    # After the packages, because the app starts downloading as soon as it reads this.
    gh('release', 'upload', tag, str(manifest), '--clobber')
    # Last, so whoever sees a Windows line in the checksums also finds its file.
    gh('release', 'upload', tag, str(checksums), '--clobber')
    print(f'Published the Windows files on {tag}')
    close_report(tag)


def report():
    """A workflow_run failure may not email the owner, so it leaves one Issue per release."""
    tag = os.getenv('TAG', '')
    run = os.environ['GITHUB_RUN_ID']
    url = f'{os.environ["GITHUB_SERVER_URL"]}/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{run}'
    title = issue_title(tag or f'运行 {run}')
    target = f'`{tag}`' if tag else '这次发布'
    body = (f'{target}的 Windows 构建或上传失败，Android 发布不受影响。\n\n运行：{url}\n\n'
            '手动重试：在 Actions 里运行 `windows.yaml`（Windows build），分支选 `main`，`release_tag` 填这个标签。')
    stamp_text = f'<!-- flclash-windows-run {run} -->'
    for issue in bot_issues('open'):
        if issue['title'] == title:
            comment_once(issue['number'], stamp_text, body)
            return
    api(f'{GH}/issues', 'POST', {'title': title, 'assignees': [OWNER], 'body': body + '\n\n' + stamp_text})


if __name__ == '__main__':
    commands = {'plan': plan, 'stamp': stamp, 'package': package, 'publish': publish, 'report': report}
    commands[sys.argv[1]]()
