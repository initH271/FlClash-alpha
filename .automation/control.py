import base64
import hashlib
import hmac
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tool.release_identity import next_release, release_identity, verify_native_identity  # noqa: E402

POLICY = json.loads((ROOT / '.automation/policy.json').read_text())
GH = 'https://api.github.com/repos/' + POLICY['github']
CNB = 'https://api.cnb.cool/' + POLICY['cnb'] + '/-'
# A review opened before CI settled counts as green only while the pipelines it could not see run.
CI_GRACE = 'FlClash/review-before-ci'
# A fetch of pinned commits during reconcile: seconds when healthy, and one hung remote must not hold the whole round.
FETCH_TIMEOUT = 120
GIT_TIMED_OUT = 124


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


def pages(url, page_key='page', size_key='page_size'):
    for page in range(1, 101):
        separator = '&' if '?' in url else '?'
        rows = api(f'{url}{separator}{page_key}={page}&{size_key}=100')
        yield from rows
        if len(rows) < 100:
            return
    raise RuntimeError('Pagination exceeded safe limit')


def check_name(status):
    return status['context'].split('(')[-1].rstrip(')')


def gating_statuses(checks):
    return [item for item in (checks or {}).get('statuses') or [] if check_name(item) != CI_GRACE]


def git(*args, check=True, env=None, timeout=None):
    try:
        result = subprocess.run(['git', *args], cwd=ROOT, env=env, text=True,
                                capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(['git', *args], GIT_TIMED_OUT, '', f'timed out after {timeout}s')
    if check and result.returncode:
        raise RuntimeError(f'git {args[0]} failed: {result.stderr[-1500:]}')
    return result.stdout.strip() if check else result


def sign(payload):
    key = os.environ['UPSTREAM_APPROVAL_KEY'].encode()
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return {'payload': payload, 'signature': hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()}


def verify(envelope):
    if not hmac.compare_digest(sign(envelope['payload'])['signature'], envelope['signature']):
        raise ValueError('Automation authorization was modified')
    return envelope['payload']


def marker(payload):
    return '<!-- flclash-upstream ' + json.dumps(sign(payload)) + ' -->'


def parse_request(body):
    match = re.search(r'<!-- flclash-upstream (\{[^\r\n]+\}) -->', body)
    return verify(json.loads(match[1])) if match else None


def approved(comment, tag):
    author = comment.get('author') or {}
    return (author.get('username') == POLICY['approver']
            and author.get('is_npc') is False
            and comment.get('body', '').strip().casefold() in ('ok', f'ok {tag}'.casefold()))


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


def comment(number, body, work_mode=False):
    return api(f'{CNB}/issues/{number}/comments', 'POST', {'body': body, 'work_mode': work_mode})


def all_issues():
    for state in ('open', 'closed'):
        yield from pages(f'{CNB}/issues?state={state}')


def paired_review(base, head, primary='审查助手'):
    if primary not in ('审查助手', '上游更新助手'):
        raise ValueError('Unexpected primary reviewer')
    return (f'本次结对审核固定范围：base `{base}`，head `{head}`。'
            '先独立核对代码，再比较两份结论。请列出证据、阻断问题、分歧及未验证项；'
            '只读审核，不编译 APK、不回复 OK、不合并或发版、不互相召唤。\n\n'
            f'@{POLICY["cnb"]}({primary}) 请完成 DeepSeek 独立审核。\n\n'
            f'@{POLICY["cnb"]}(GLM复核助手) 请独立复核同一范围，重点寻找遗漏和反例。')


def in_progress(number, tag):
    # Any doubt counts as in progress: an unreadable candidate or branch error keeps the issue open.
    if any(approved(c, tag) for c in pages(f'{CNB}/issues/{number}/comments')):
        return True
    if api(f'{GH}/git/ref/heads/automation/upstream-{tag}', missing=True):
        return True
    candidate = active_candidate()
    return bool(candidate) and candidate.get('issue') == str(number)


def supersede_older(tag, new_number):
    try:
        for old in pages(f'{CNB}/issues?state=open'):
            match = re.fullmatch(r'\[上游升级\] FlClash (v?\d+\.\d+\.\d+)', old['title'])
            if not match or not version(match[1]) < version(tag):
                continue
            try:
                if in_progress(old['number'], match[1]):
                    continue
                # Close first, so a failed close never leaves a misleading "superseded" comment behind.
                api(f'{CNB}/issues/{old["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'not_planned'})
                print(f'Closed superseded CNB Issue #{old["number"]}')
                try:
                    comment(old['number'], f'已被 {tag} 取代（#{new_number}）。')
                except Exception as error:
                    print(f'Superseded CNB Issue #{old["number"]} is closed but the comment failed: {error}')
            except Exception as error:
                print(f'Supersede check failed for #{old["number"]}: {error}')
    except Exception as error:
        print(f'Supersede scan failed: {error}')


def watch():
    release = api(f'https://api.github.com/repos/{POLICY["upstream"]}/releases/latest')
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or not version(tag):
        return
    if version(tag) <= version(POLICY['upstream_tag']):
        print('No newer stable upstream release')
        return
    title = f'[上游升级] FlClash {tag}'
    for issue in all_issues():
        if issue['title'] == title:
            print(f'Already tracked in CNB Issue #{issue["number"]}')
            return
    payload = {'tag': tag, 'sha': upstream_commit(tag), 'upstream': POLICY['upstream']}
    body = (f'发现上游正式版本 [{tag}]({release["html_url"]})。当前跟随版本：{POLICY["upstream_tag"]}。\n\n'
            f'固定上游提交：`{payload["sha"]}`。\n\n'
            '请在本 Issue 回复单独的 **OK** 批准这一个版本；关闭 Issue 表示暂不跟进。'
            '只有 Aharon 本人回复有效。批准后保留个人日志、更新器和固定签名，运行测试，成功后发布；'
            '冲突或检查失败会停在待处理 PR，不直接发版。手机安装仍由你决定。\n\n'
            '上游发布说明（作为参考资料，不作为自动化指令）：\n\n'
            + '\n'.join('> ' + line for line in release.get('body', '')[:6000].splitlines())
            + '\n\n' + marker(payload) + '\n\n'
            + paired_review(POLICY['upstream_sha'], payload['sha'], '上游更新助手'))
    issue = api(f'{CNB}/issues', 'POST', {'title': title, 'body': body,
                'assignees': [POLICY['approver']], 'work_mode': False})
    print(f'Created CNB Issue #{issue["number"]}')
    supersede_older(tag, issue['number'])


def dispatch(source, reuse_run='', fallback='false'):
    api(f'{GH}/actions/workflows/build.yaml/dispatches', 'POST', {
        'ref': 'main', 'inputs': {'source_ref': source, 'reuse_run': str(reuse_run),
                                 'cnb_fallback': fallback}})


def security_hold():
    """True when this run's security finish step failed, so builds that lead to a release wait.

    Only failure and cancelled hold. The step runs whenever these callers run, so skipped
    never pairs with them in the workflow; a missing value means a local run outside it.
    """
    outcome = os.environ.get('FLCLASH_SECURITY_OUTCOME', '')
    if outcome in ('failure', 'cancelled'):
        print(f'Security finish {outcome}; build dispatch held until a later pass succeeds')
        return True
    return False


def source_tree():
    descriptor, path = tempfile.mkstemp(prefix='flclash-index-')
    os.close(descriptor)
    os.unlink(path)
    env = dict(os.environ, GIT_INDEX_FILE=path)
    try:
        git('read-tree', 'HEAD', env=env)
        git('update-index', '--force-remove', '.automation/candidate.json', env=env)
        return git('write-tree', env=env)
    finally:
        pathlib.Path(path).unlink(missing_ok=True)


def validate_source(check_reviews=True):
    head = git('rev-parse', 'HEAD')
    main = api(f'{GH}/git/ref/heads/main')['object']['sha']
    if head == main:
        return None
    candidate = active_candidate()
    if not candidate:
        raise ValueError('Source is not main and carries no approved candidate')
    if candidate['tree'] != source_tree() or candidate['base'] != main:
        raise ValueError('Candidate changed or main advanced; review/rebase required')
    detail = api(f'{CNB}/issues/{candidate["issue"]}')
    request = parse_request(detail['body'])
    if detail['state'] != 'open' or request['sha'] != candidate['upstream_sha']:
        raise ValueError('Upgrade approval was withdrawn or changed')
    if not any(approved(c, request['tag']) for c in pages(f'{CNB}/issues/{candidate["issue"]}/comments')):
        raise ValueError('Owner approval is missing')
    if check_reviews:
        from reviews import require_candidate
        require_candidate(head, main)
    return candidate


def active_candidate(released=False):
    """Return the signed candidate on disk, or None once it is finished; any doubt keeps it active.

    Finished means its upgrade issue is closed, or (unless the caller is finishing a release) its upstream
    commit is in main and the version in release.json, which names that upstream, is published as a
    non-draft release. The file stays on main until the next prepare_candidate overwrites it.
    """
    path = ROOT / '.automation/candidate.json'
    if not path.exists():
        return None
    candidate = verify(json.loads(path.read_text()))
    try:
        issue = api(f'{CNB}/issues/{candidate["issue"]}', missing=True)
        if issue and issue['state'] == 'closed':
            return None
        if released or not issue:
            return candidate
        request = parse_request(issue['body'])
        metadata = json.loads((ROOT / '.github/release.json').read_text())
        if (not request or request['sha'] != candidate['upstream_sha']
                or metadata.get('upstreamVersion') != request['tag'].removeprefix('v')):
            return candidate
        main = api(f'{GH}/git/ref/heads/main')['object']['sha']
        if git('merge-base', '--is-ancestor', candidate['upstream_sha'], main, check=False).returncode:
            return candidate
        release = api(f'{GH}/releases/tags/{release_identity(metadata)["tag"]}', missing=True)
    except (HttpStatusError, ValueError, KeyError, TypeError):
        return candidate
    return None if release and release.get('draft') is False else candidate


def adopt_owner_merge(sha, branch, number):
    """The owner merged the approved upstream into main by hand: prepare on top of the conflict branch."""
    request = parse_request(api(f'{CNB}/issues/{number}')['body'])
    git('fetch', 'origin', 'main')
    if (not request or request.get('upstream') != POLICY['upstream']
            or git('merge-base', '--is-ancestor', request['sha'], 'origin/main', check=False).returncode
            or upstream_commit(request['tag']) != request['sha']):
        return
    prepare_candidate(request, number, branch, previous=sha)


def approvals():
    import reviews
    for issue in pages(f'{CNB}/issues?state=open'):
        if not issue['title'].startswith('[上游升级] '):
            continue
        detail = api(f'{CNB}/issues/{issue["number"]}')
        try:
            request = parse_request(detail['body'])
        except (ValueError, KeyError):
            continue
        if not request or request.get('upstream') != POLICY['upstream']:
            continue
        if not version(request['tag']) or version(request['tag']) <= version(POLICY['upstream_tag']):
            continue
        comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
        if not any(approved(c, request['tag']) for c in comments):
            continue
        branch = f'automation/upstream-{request["tag"]}'
        existing = api(f'{GH}/git/ref/heads/{branch}', missing=True)
        if existing:
            resume_candidate(existing['object']['sha'], branch, issue['number'])
            continue
        if upstream_commit(request['tag']) != request['sha']:
            comment(issue['number'], '上游标签指向已变化，暂停升级，请重新核实该版本。')
            continue
        prepare_candidate(request, issue['number'], branch)
        return


def resume_candidate(sha, branch, number):
    from reviews import reconcile
    runs = api(f'{GH}/actions/workflows/build.yaml/runs?per_page=100')['workflow_runs']
    if any(sha in run['display_title'] and run['status'] != 'completed' for run in runs):
        return
    git('fetch', 'origin', branch)
    git('checkout', '-B', branch, 'FETCH_HEAD')
    if git('rev-parse', 'HEAD') != sha:
        print('Candidate branch advanced while fetching; retry next controller pass')
        return
    path = ROOT / '.automation/candidate.json'
    candidate = active_candidate()
    own = path.exists() and verify(json.loads(path.read_text()))['issue'] == str(number)
    # Only a conflict branch is adopted. It may inherit the finished candidate main keeps until the next prepare.
    if (ROOT / 'UPSTREAM_REVIEW.md').exists() and not candidate and not own:
        adopt_owner_merge(sha, branch, number)
        return
    if not candidate or not own:
        return
    main = api(f'{GH}/git/ref/heads/main')['object']['sha']
    if candidate['base'] != main:
        refresh_candidate(candidate, sha, branch, number, main)
        return
    if any(sha in run['display_title'] for run in runs):
        return
    try:
        validate_source(check_reviews=False)
    except ValueError as error:
        print(f'Candidate authorization invalid: {error}')
        return
    sync_branch(branch)
    pulls = api(f'{GH}/pulls?state=open&head={POLICY["github"].split("/")[0]}:{branch}')
    if not pulls:
        api(f'{GH}/pulls', 'POST', {'head': branch, 'base': 'main', 'draft': True,
            'title': f'Resume approved {branch}', 'body': f'Approved in CNB Issue #{number}.'})
    reconcile()
    try:
        validate_source()
    except ValueError as error:
        print(f'Candidate waiting: {error}')
        return
    if security_hold():
        return
    dispatch(sha)


def refresh_candidate(candidate, sha, branch, number, main):
    if candidate['tree'] != source_tree():
        print('Candidate contains unsigned changes; automatic refresh refused')
        return
    issue = api(f'{CNB}/issues/{number}')
    request = parse_request(issue['body'])
    if (issue['state'] != 'open' or not request
            or request.get('upstream') != POLICY['upstream']
            or request['sha'] != candidate['upstream_sha']
            or not any(approved(c, request['tag']) for c in pages(f'{CNB}/issues/{number}/comments'))):
        print('Candidate approval was withdrawn or changed; refresh refused')
        return
    if upstream_commit(request['tag']) != request['sha']:
        print('Upstream tag moved; refresh refused')
        return
    git('fetch', 'origin', 'main')
    if git('rev-parse', 'origin/main') != main:
        print('Main advanced again; retry next controller pass')
        return
    if git('merge-base', '--is-ancestor', candidate['base'], main, check=False).returncode:
        print('Main history was rewritten; manual review required')
        return
    prepare_candidate(request, number, branch, previous=sha)


def commit_candidate(branch, base, previous=None):
    git('commit', '-m', 'feat(upstream): prepare approved upstream candidate')
    if previous:
        sha = git('commit-tree', git('rev-parse', 'HEAD^{tree}'), '-p', previous, '-p', base,
                  '-m', 'chore(upstream): refresh approved candidate on latest main')
        git('checkout', '-B', branch, sha)


def listed(paths, limit=10):
    rows = ''.join(f'\n- `{p}`' for p in paths[:limit])
    return rows + (f'\n- 另有 {len(paths) - limit} 个未列出' if len(paths) > limit else '')


def ask_owner_merge(request, number, branch, url, conflicts, protected):
    """Hand a conflicting upgrade to the owner, once per approved upstream commit; no NPC can merge it."""
    stamp = '<!-- flclash-owner-merge ' + json.dumps(sign({'issue': str(number), 'upstream_sha': request['sha']})) + ' -->'
    if any(stamp in c.get('body', '') for c in pages(f'{CNB}/issues/{number}/comments')):
        return
    conflicts = sorted(set(conflicts))
    protected = sorted(set(protected) - set(conflicts))
    comment(number, f'上游 {request["tag"]} 自动合并已停止：有 {len(conflicts)} 个冲突文件和 {len(protected)} 个受保护文件，'
            '需要 owner 人工合并上游。\n\n冲突文件：' + (listed(conflicts) or '无') + '\n\n受保护文件：' + (listed(protected) or '无')
            + f'\n\n请把上游提交 `{request["sha"]}` 合进 main，`.automation/policy.json` 和 `.github/release.json` 留给控制器写入，'
            f'步骤见 AUTOMATION.md 的 Conflicting upstream upgrades 一节。合进 main 后在本 Issue 回复 OK，控制器会在升级分支 `{branch}` 上'
            f'准备候选并发版，记录冲突的草稿 PR {url} 继续沿用。\n\n' + stamp)


def prepare_candidate(request, number, branch, previous=None):
    from reviews import reconcile
    git('fetch', 'origin', 'main')
    git('checkout', '-B', branch, 'origin/main')
    base = git('rev-parse', 'HEAD')
    git('fetch', '--no-tags', f'https://github.com/{POLICY["upstream"]}.git', request['sha'])
    result = git('merge', '--no-ff', '--no-commit', request['sha'], check=False)
    conflicts = git('diff', '--name-only', '--diff-filter=U').splitlines()
    touched = git('diff', '--cached', '--name-only').splitlines()
    protected = [p for p in touched if any(p == x or p.startswith(x) for x in POLICY['protected_paths'])]
    if result.returncode or conflicts or protected:
        git('merge', '--abort', check=False)
        if previous:
            message = f'候选刷新暂停：main `{base}` 与已批准上游存在冲突或受保护文件改动，原分支未覆盖。'
            if not any(c['body'] == message for c in pages(f'{CNB}/issues/{number}/comments')):
                comment(number, message)
            return
        report = ROOT / 'UPSTREAM_REVIEW.md'
        report.write_text(f'# Upstream {request["tag"]} needs review\n\n'
                          f'Upstream commit: {request["sha"]}\n\n'
                          + '\n'.join('- ' + p for p in sorted(set(conflicts + protected)))
                          + '\n\nNo upstream changes have been merged into this branch yet.\n', encoding='utf-8')
        git('add', 'UPSTREAM_REVIEW.md')
        git('commit', '-m', f'docs(upstream): record conflicts for {request["tag"]}')
        git('push', 'origin', branch)
        pr = api(f'{GH}/pulls', 'POST', {'head': branch, 'base': 'main', 'draft': True,
                 'title': f'跟进上游 {request["tag"]}：需要处理合并冲突',
                 'body': f'Owner approved CNB Issue #{number}. No automatic merge: inspect UPSTREAM_REVIEW.md.'})
        sync_branch(branch)
        ask_owner_merge(request, number, branch, pr['html_url'], conflicts, protected)
        return
    release = next_release(json.loads((ROOT / '.github/release.json').read_text()),
                          upstream=request['tag'].removeprefix('v'))
    (ROOT / '.github/release.json').write_text(json.dumps(release, indent=2) + '\n')
    policy = dict(POLICY, upstream_tag=request['tag'], upstream_sha=request['sha'])
    (ROOT / '.automation/policy.json').write_text(json.dumps(policy, indent=2) + '\n')
    (ROOT / '.github/release-notes.md').write_text(
        f'跟随上游 {request["tag"]}，保留滚动日志、双渠道更新和固定个人签名。\n', encoding='utf-8')
    git('add', '-A')
    git('update-index', '--force-remove', '.automation/candidate.json')
    tree = git('write-tree')
    payload = {'issue': str(number), 'base': base, 'tree': tree, 'upstream_sha': request['sha']}
    (ROOT / '.automation/candidate.json').write_text(json.dumps(sign(payload), indent=2) + '\n')
    git('add', '.automation/candidate.json')
    commit_candidate(branch, base, previous)
    git('push', 'origin', branch)
    sync_branch(branch)
    pulls = api(f'{GH}/pulls?state=open&head={POLICY["github"].split("/")[0]}:{branch}')
    pr = pulls[0] if pulls else api(f'{GH}/pulls', 'POST', {'head': branch, 'base': 'main', 'draft': True,
             'title': f'跟进上游 {request["tag"]}，保留个人增强功能',
             'body': f'Approved in CNB Issue #{number}. Preserve personal logging and update features; tests and paired reviews gate publication.'})
    comment(number, f'已按本次 OK 批准准备升级分支：{pr["html_url"]}。等待 PR 双模型审核通过后，再测试、构建并发布。')
    reconcile()


def sync_branch(branch, source='HEAD'):
    token = os.environ['CNB_AUTOMATION_TOKEN']
    encoded = base64.b64encode(f'cnb:{token}'.encode()).decode()
    env = dict(os.environ, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://cnb.cool/.extraheader',
               GIT_CONFIG_VALUE_0='Authorization: Basic ' + encoded, GIT_TERMINAL_PROMPT='0')
    git('push', f'https://cnb.cool/{POLICY["cnb"]}.git', f'{source}:refs/heads/{branch}', env=env)


def promote():
    candidate = validate_source()
    if candidate:
        api(f'{GH}/git/refs/heads/main', 'PATCH', {'sha': git('rev-parse', 'HEAD'), 'force': False})
    sync_branch('main')


def close_published_failures():
    for issue in pages(f'{CNB}/issues?state=open'):
        match = re.fullmatch(r'\[构建待处理\] GitHub #(\d+)', issue['title'])
        author = issue.get('author') or {}
        if not match or author.get('username') != POLICY['approver'] or author.get('is_npc') is not False:
            continue
        run = api(f'{GH}/actions/runs/{match[1]}')
        source = re.fullmatch(r'Android ([0-9a-f]{40})(?: recovery)?', run['display_title'])
        if source and git('merge-base', '--is-ancestor', source[1], 'HEAD', check=False).returncode == 0:
            comment(issue['number'], '包含该候选历史的后继版本已通过验证并成功发布，关闭旧构建失败记录。')
            api(f'{CNB}/issues/{issue["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})


def notify_release():
    # The release just went out, so only a closed issue marks this candidate as finished here.
    candidate = active_candidate(released=True)
    if candidate:
        issue = api(f'{CNB}/issues/{candidate["issue"]}')
        if issue['state'] == 'open':
            comment(candidate['issue'], '测试、构建和固定签名检查通过，新版已发布到 GitHub，CNB 正在同步。手机更新请自行确认安装。')
            api(f'{CNB}/issues/{candidate["issue"]}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})
    try:
        close_published_failures()
    except (RuntimeError, KeyError) as error:
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
                'promote': promote, 'notify': notify_release, 'status': build_status}
    commands[sys.argv[1]]()
