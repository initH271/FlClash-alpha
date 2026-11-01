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
import urllib.parse
import zipfile

from control import GH, OWNER, POLICY, ROOT, api, bot_issues, comment, comment_once, release_identity

SETUP = 'FlClash-alpha-windows-amd64-setup.exe'
ARCHIVE = 'FlClash-alpha-windows-amd64.zip'
CHECKSUMS = 'SHA256SUMS.txt'
OUTPUT = 'dist-windows'
# What a running installation cannot do without, at the paths windows/CMakeLists.txt installs them to.
BUNDLE = ('FlClash.exe', 'FlClashCore.exe', 'FlClashHelperService.exe', 'flutter_windows.dll', 'data/app.so')
SKIP = {'mode': 'skip', 'source': '', 'tag': ''}


def has_windows(release):
    return {SETUP, ARCHIVE} <= {asset['name'] for asset in release['assets']}


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
    return data[at:end].decode('utf-16-le')


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
    files = (out / SETUP, out / ARCHIVE)
    merged = merge_checksums(gh('release', 'download', tag, '--pattern', CHECKSUMS, '--output', '-').decode(),
                             {path.name: sha256(path) for path in files})
    checksums = root / CHECKSUMS
    checksums.write_text(merged, encoding='utf-8')
    gh('release', 'upload', tag, *map(str, files), '--clobber')
    # Last, so whoever sees a Windows line in the checksums also finds both files.
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
