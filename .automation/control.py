import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tool.release_identity import release_identity, verify_native_identity  # noqa: E402

POLICY = json.loads((ROOT / '.automation/policy.json').read_text())
GH = 'https://api.github.com/repos/' + POLICY['github']
CNB = 'https://api.cnb.cool/' + POLICY['cnb'] + '/-'
OWNER = POLICY['github'].split('/')[0]
BOT = 'github-actions[bot]'


class HttpStatusError(RuntimeError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def api(url, method='GET', data=None, missing=False, timeout=60):
    headers = {'Accept': 'application/json', 'User-Agent': 'FlClash-alpha-automation'}
    host = urllib.parse.urlsplit(url).netloc
    token = os.getenv('GH_TOKEN') if host == 'api.github.com' else (
        os.getenv('CNB_AUTOMATION_TOKEN') or os.getenv('CNB_TOKEN')
        if host == 'api.cnb.cool' else None)
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if data is not None:
        data = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, data=data, headers=headers, method=method), timeout=timeout) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        if missing and error.code == 404:
            return None
        try:
            detail = json.loads(error.read())
            reason = str(detail.get('message', detail.get('errmsg', '')))[:300]
        except (ValueError, AttributeError):
            reason = ''
        if token:
            reason = reason.replace(token, '***')
        raise HttpStatusError(f'{method} {host} returned HTTP {error.code}: {reason}', error.code) from None


def pages(url, page_key='page', size_key='per_page'):
    for page in range(1, 101):
        separator = '&' if '?' in url else '?'
        rows = api(f'{url}{separator}{page_key}={page}&{size_key}=100')
        yield from rows
        if len(rows) < 100:
            return
    raise RuntimeError('Pagination exceeded safe limit')


def git(*args, check=True, env=None):
    result = subprocess.run(['git', *args], cwd=ROOT, env=env, text=True,
                            capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f'git {args[0]} failed: {result.stderr[-1500:]}')
    return result.stdout.strip() if check else result


def marker(payload):
    return '<!-- flclash-upstream ' + json.dumps(payload) + ' -->'


def parse_request(body):
    """Read the record the bot wrote on a line of its own. Only an author check makes it trustworthy: see upstream_request."""
    found = re.findall(r'^<!-- flclash-upstream (\{[^\r\n]+\}) -->$', body or '', re.M)
    try:
        request = json.loads(found[-1]) if found else None
    except ValueError:
        return None
    if not isinstance(request, dict) or not all(isinstance(request.get(k), str) for k in ('tag', 'sha', 'upstream')):
        return None
    return request


def upstream_request(issue):
    """The upgrade an Issue records, or None. Anyone can open an Issue, and only the bot can be this author."""
    if (issue.get('user') or {}).get('login') != BOT or issue.get('pull_request') is not None:
        return None
    request = parse_request(issue.get('body'))
    if (not request or request['upstream'] != POLICY['upstream'] or not version(request['tag'])
            or issue.get('title') != upstream_title(request['tag'])):
        return None
    return request


def approved(comment, tag):
    """Only the repository owner in person, by login and by association, with nothing else in the comment."""
    author = comment.get('user') or {}
    return (author.get('login') == OWNER and author.get('type') == 'User'
            and comment.get('author_association') == 'OWNER'
            and (comment.get('body') or '').strip().casefold() in ('ok', f'ok {tag}'.casefold()))


def version(tag):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', tag)
    return tuple(map(int, match.groups())) if match else None


def upstream_commit(tag):
    obj = api(f'https://api.github.com/repos/{POLICY["upstream"]}/git/ref/tags/'
              + urllib.parse.quote(tag, safe=''))['object']
    for _ in range(5):
        if obj['type'] == 'commit':
            return obj['sha']
        obj = api(f'https://api.github.com/repos/{POLICY["upstream"]}/git/tags/{obj["sha"]}')['object']
    raise ValueError('Unresolvable upstream tag')


def comment(number, body):
    return api(f'{GH}/issues/{number}/comments', 'POST', {'body': body})


def stamped(number, stamp):
    """Anyone can paste a stamp, so only the bot's own comments count."""
    return any(stamp in (c.get('body') or '') and (c.get('user') or {}).get('login') == BOT
               for c in pages(f'{GH}/issues/{number}/comments'))


def comment_once(number, stamp, body):
    if not stamped(number, stamp):
        comment(number, body + '\n\n' + stamp)


def bot_issues(state):
    for issue in pages(f'{GH}/issues?state={state}&creator=github-actions%5Bbot%5D'):
        if (issue.get('user') or {}).get('login') == BOT and issue.get('pull_request') is None:
            yield issue


def upstream_title(tag):
    return f'[上游升级] FlClash {tag}'


def analyze(number, tag, sha):
    """Ask the NPC for a read-only analysis. It is only advice: failing costs one comment, not the Issue."""
    try:
        api(f'{GH}/actions/workflows/npc-upstream.yml/dispatches', 'POST', {'ref': 'main', 'inputs': {
            'issue': str(number), 'tag': tag, 'base': POLICY['upstream_sha'], 'head': sha}})
    except (RuntimeError, OSError) as error:
        print(f'No NPC analysis for Issue #{number}: {error}')


def watch():
    release = api(f'https://api.github.com/repos/{POLICY["upstream"]}/releases/latest')
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or not version(tag):
        return
    if version(tag) <= version(POLICY['upstream_tag']):
        print('No newer stable upstream release')
        return
    title = upstream_title(tag)
    for issue in bot_issues('all'):
        if issue['title'] == title:
            print(f'Already tracked in Issue #{issue["number"]}')
            return
    payload = {'tag': tag, 'sha': upstream_commit(tag), 'upstream': POLICY['upstream']}
    # Upstream's release text stays behind the link: pasted here, its mentions and links would notify people.
    body = (f'发现上游正式版本 [{tag}](https://github.com/{POLICY["upstream"]}/releases/tag/{tag})。'
            f'当前跟随版本：{POLICY["upstream_tag"]}。\n\n'
            f'固定上游提交：`{payload["sha"]}`。\n\n'
            '请在本 Issue 回复单独的 **OK** 批准这一个版本；关闭 Issue 表示暂不跟进。只有仓库 owner 本人回复有效。'
            '批准后会开一个普通 PR，有冲突时只报告，不合并。合并这个 PR 不发版，发版另开改版本号的 PR。\n\n'
            + marker(payload))
    issue = api(f'{GH}/issues', 'POST', {'title': title, 'body': body, 'assignees': [OWNER]})
    print(f'Created Issue #{issue["number"]}')
    analyze(issue['number'], tag, payload['sha'])


def dispatch(source, reuse_run=''):
    api(f'{GH}/actions/workflows/build.yaml/dispatches', 'POST', {
        'ref': 'main', 'inputs': {'source_ref': source, 'reuse_run': str(reuse_run)}})


def validate_source():
    """Only the current main builds and publishes; a change reaches main through a merged pull request."""
    if git('rev-parse', 'HEAD') != api(f'{GH}/git/ref/heads/main')['object']['sha']:
        raise ValueError('Source is not the current main')


def approvals():
    """Act on an owner OK. ISSUE_NUMBER narrows a comment-triggered run to that Issue; the hourly pass checks them all."""
    number = os.getenv('ISSUE_NUMBER')
    issues = [api(f'{GH}/issues/{int(number)}')] if number else bot_issues('open')
    for issue in issues:
        request = upstream_request(issue)
        if issue['state'] != 'open' or not request or version(request['tag']) <= version(POLICY['upstream_tag']):
            continue
        number = issue['number']
        if not any(approved(c, request['tag']) for c in pages(f'{GH}/issues/{number}/comments')):
            continue
        branch = f'agent/upstream-{request["tag"]}'
        if api(f'{GH}/git/ref/heads/{branch}', missing=True):
            open_pull_request(request, number, branch)
            continue
        if upstream_commit(request['tag']) != request['sha']:
            comment_once(number, f'<!-- flclash-tag-moved {request["sha"]} -->', '上游标签指向已变化，暂停升级，请重新核实该版本。')
            continue
        prepare_upgrade(request, number, branch)


def listed(paths, limit=10):
    rows = ''.join(f'\n- `{p}`' for p in paths[:limit])
    return rows + (f'\n- 另有 {len(paths) - limit} 个未列出' if len(paths) > limit else '')


def conflict_stamp(request):
    return f'<!-- flclash-owner-merge {request["sha"]} -->'


def report_conflict(request, number, conflicts, protected):
    """Hand a conflicting upgrade to the owner, once per approved upstream commit. Nothing is pushed."""
    conflicts = sorted(set(conflicts))
    protected = sorted(set(protected) - set(conflicts))
    comment_once(number, conflict_stamp(request),
                 f'上游 {request["tag"]} 没有自动合并：有 {len(conflicts)} 个冲突文件和 {len(protected)} 个受保护文件，需要人工处理。\n\n'
                 '冲突文件：' + (listed(conflicts) or '无') + '\n\n受保护文件：' + (listed(protected) or '无')
                 + f'\n\n要合并的上游提交：`{request["sha"]}`。步骤见 AUTOMATION.md 的 Conflicting upstream upgrades 一节，'
                 f'开出的 PR 正文写上 `Closes #{number}`。这条报告只发一次，之后不再自动重试。')


def prepare_upgrade(request, number, branch):
    """Merge the approved upstream on a new branch and open a PR. A reported conflict is not retried."""
    if stamped(number, conflict_stamp(request)):
        return
    git('fetch', 'origin', 'main')
    git('checkout', '-B', branch, 'origin/main')
    git('fetch', '--no-tags', f'https://github.com/{POLICY["upstream"]}.git', request['sha'])
    result = git('merge', '--no-ff', '--no-commit', request['sha'], check=False)
    conflicts = git('diff', '--name-only', '--diff-filter=U').splitlines()
    touched = git('diff', '--cached', '--name-only').splitlines()
    protected = [p for p in touched if any(p == x or p.startswith(x) for x in POLICY['protected_paths'])]
    if result.returncode or conflicts or protected:
        git('merge', '--abort', check=False)
        report_conflict(request, number, conflicts, protected)
        return
    # The version number and release notes are a later PR of their own (D3): merging this one publishes nothing.
    policy = dict(POLICY, upstream_tag=request['tag'], upstream_sha=request['sha'])
    (ROOT / '.automation/policy.json').write_text(json.dumps(policy, indent=2) + '\n')
    git('add', '.automation/policy.json')
    git('commit', '-m', f'feat(upstream): follow {request["tag"]}')
    git('push', 'origin', branch)
    open_pull_request(request, number, branch)


def open_pull_request(request, number, branch):
    """Open the one PR of this branch. A closed PR stays closed: the owner decided, and deleting the branch starts over."""
    if api(f'{GH}/pulls?state=all&head={OWNER}:{branch}'):
        return
    approve = ('这个 PR 由机器人开，CI 要 owner 放行：在 PR 的合并框点 **Approve workflows to run**'
               '（也可以关闭再重开），然后等 `ci-ok` 和 `Dependency vulnerability scan`。')
    pr = api(f'{GH}/pulls', 'POST', {
        'head': branch, 'base': 'main', 'title': f'跟进上游 {request["tag"]}，保留个人增强功能',
        'body': f'Closes #{number}.\n\n{approve}\n\n合并后不发版，发版另开改 `.github/release.json` 和 '
                '`.github/release-notes.md` 的 PR。有用户可见的界面变化时，合并前先发截图给 owner。'})
    comment(number, f'已按本次 OK 开出升级 PR：{pr["html_url"]}。{approve}')


def sync_branch(branch, source='HEAD'):
    token = os.environ['CNB_AUTOMATION_TOKEN']
    encoded = base64.b64encode(f'cnb:{token}'.encode()).decode()
    env = dict(os.environ, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://cnb.cool/.extraheader',
               GIT_CONFIG_VALUE_0='Authorization: Basic ' + encoded, GIT_TERMINAL_PROMPT='0')
    git('push', f'https://cnb.cool/{POLICY["cnb"]}.git', f'{source}:refs/heads/{branch}', env=env)


def promote():
    validate_source()
    sync_branch('main')


def sync_main():
    """Bring CNB main up to GitHub main, which carries the mirror and NPC pipelines; promote only runs for a release."""
    base = api(f'{GH}/git/ref/heads/main')['object']['sha']
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', base)
    git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git', 'refs/heads/main')
    source = git('rev-parse', 'FETCH_HEAD')
    if source == base:
        return
    if git('merge-base', '--is-ancestor', source, base, check=False).returncode != 0:
        # Fail the step so the owner hears of it: a stale CNB main silently keeps old mirror and NPC pipelines.
        raise ValueError('CNB main is not behind GitHub main; leaving both unchanged')
    sync_branch('main', base)


def close_published_failures():
    for issue in bot_issues('open'):
        match = re.fullmatch(r'\[构建待处理\] GitHub #(\d+)', issue['title'])
        if not match:
            continue
        run = api(f'{GH}/actions/runs/{match[1]}')
        source = re.fullmatch(r'Android ([0-9a-f]{40})(?: recovery)?', run['display_title'])
        if source and git('merge-base', '--is-ancestor', source[1], 'HEAD', check=False).returncode == 0:
            comment(issue['number'], '包含这次构建历史的后继版本已通过验证并成功发布，关闭旧的构建失败记录。')
            api(f'{GH}/issues/{issue["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})


def notify_release():
    # The release is already public: tidying old Issues must never stop the mirror from being told.
    try:
        close_published_failures()
    except (RuntimeError, KeyError, OSError) as error:
        print(f'Published successfully; old failure Issue cleanup needs retry: {error}')
    api(f'{CNB}/build/start', 'POST', {'branch': 'main', 'event': 'api_trigger', 'sync': 'false',
                                     'title': 'Mirror newly published signed release'})


def build_status():
    state = os.environ.get('BUILD_STATUS', 'pending')
    if state not in ('pending', 'success', 'failure'):
        state = 'error'
    api(f'{GH}/statuses/{git("rev-parse", "HEAD")}', 'POST', {
        'state': state, 'context': 'FlClash/approved-build',
        'target_url': f'https://github.com/{POLICY["github"]}/actions/runs/{os.environ["GITHUB_RUN_ID"]}',
        'description': 'Tests, exact-source APK and personal signing'})


if __name__ == '__main__':
    commands = {'watch': watch, 'approvals': approvals, 'validate': validate_source,
                'promote': promote, 'sync': sync_main, 'notify': notify_release, 'status': build_status}
    commands[sys.argv[1]]()
