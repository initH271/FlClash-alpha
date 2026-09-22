import base64
import hashlib
import json
import os
import re
import tomllib

from control import CNB, GH, POLICY, api, comment, git, pages, sign, sync_branch, verify
from reviews import find_request, result, scope, state, reconcile as review_reconcile
from security_groups import GROUPS, repair_branch
from security_watch import active_developer, record

PATHS = {'go-core': {'core/go.mod', 'core/go.sum'},
         'rust-helper': {'services/helper/Cargo.lock'},
         'rust-api': {'plugins/rust_api/rust/Cargo.lock'}}
CHECKS = {'Dependency vulnerability gate', 'Go dependency regression tests',
          'Rust dependency regression tests', 'Paired review gate'}


def compatible(old, new):
    def version(text):
        match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', text)
        return tuple(map(int, match.groups())) if match else None
    a, b = version(old), version(new)
    return bool(a and b and b >= a and a[0] == b[0] and (a[0] != 0 or a[1] == b[1]))


def safe_files(base, head, group=None):
    paths = set(filter(None, git('diff', '--name-only', '-z', f'{base}...{head}').split('\0')))
    allowed = PATHS[group] if group else set().union(*PATHS.values())
    if not paths or not paths <= allowed:
        return False
    if paths == {'core/go.sum'}:
        return False
    for path in paths:
        if path.endswith('go.sum'):
            continue
        old, new = (git('show', f'{sha}:{path}') for sha in (base, head))
        if path.endswith('go.mod'):
            pattern = r'(?m)^(\s*[\w./~+\-]+\s+)(v\d+[^\s]*)([^\r\n]*)$'
            before, after = re.findall(pattern, old), re.findall(pattern, new)
            if re.sub(pattern, r'\1VERSION\3', old) != re.sub(pattern, r'\1VERSION\3', new):
                return False
            if len(before) != len(after) or any(a != b and not compatible(a[1], b[1]) for a, b in zip(before, after)):
                return False
        else:
            def versions(text):
                rows = {}
                for package in tomllib.loads(text)['package']:
                    rows.setdefault((package['name'], package.get('source', '')), set()).add(package['version'])
                return rows
            before, after = versions(old), versions(new)
            registries = {source for _, source in before if source.startswith('registry+')}
            if any(source not in registries for _, source in after.keys() - before.keys()):
                return False
            for name in before.keys() & after.keys():
                if before[name] == after[name]:
                    continue
                if len(before[name]) != 1 or len(after[name]) != 1 or not compatible(next(iter(before[name])), next(iter(after[name]))):
                    return False
    return True


def passed_checks(number, request=None):
    checks = api(f'{CNB}/pulls/{number}/commit-statuses')
    statuses = checks.get('statuses', [])
    names = {s['context'].split('(')[-1].rstrip(')') for s in statuses if s['state'] == 'success'}
    passed = checks.get('state') == 'success' and CHECKS <= names and all(s['state'] == 'success' for s in statuses)
    if not passed or request is None:
        return passed
    sha = checks.get('sha', '')
    if not re.fullmatch(r'[a-f0-9]{40}', sha):
        return False
    git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git', sha, request['base'], request['head'])
    merged = git('merge-tree', '--write-tree', request['base'], request['head'], check=False)
    return merged.returncode == 0 and git('rev-parse', sha + '^{tree}') == merged.stdout.splitlines()[0]


def notify_once(issue, identity, message):
    marker = '<!-- security-finish-attention ' + hashlib.sha256(identity.encode()).hexdigest() + ' -->'
    comments = pages(f'{CNB}/issues/{issue["number"]}/comments')
    if not any(c.get('author', {}).get('username') == POLICY['approver']
               and c.get('author', {}).get('is_npc') is False and marker in c.get('body', '') for c in comments):
        comment(issue['number'], marker + '\n\n' + message)


def mirror_record(pull):
    match = re.search(r'<!-- flclash-security-mirror (\{[^\r\n]+\}) -->', pull.get('body', ''))
    if not match:
        return None
    try:
        return verify(json.loads(match[1]))
    except (ValueError, KeyError, TypeError):
        return None


def mirror_attestation(pull):
    payload = mirror_record(pull)
    if not payload or 'cnb_number' not in payload or pull.get('draft'):
        return None
    digest = hashlib.sha256((payload['base'] + payload['head']).encode()).hexdigest()[:16]
    branch = payload.get('branch') or 'automation/security-sync-' + digest
    if (pull['base']['ref'] != 'main' or pull['head']['repo']['full_name'] != POLICY['github']
            or pull['head']['ref'] != branch or pull['base']['sha'] != payload['base']
            or pull['head']['sha'] != payload['head']):
        return None
    source = api(f'{CNB}/pulls/{payload["cnb_number"]}')
    if (source['state'] != 'open' or source.get('is_wip')
            or source['head']['repo']['path'] != POLICY['cnb']
            or source['base']['ref'] != 'refs/heads/main'
            or source['base']['sha'] != payload['base'] or source['head']['sha'] != payload['head']):
        return None
    request = scope('cnb', source)
    if state(request) != 'success' or not passed_checks(source['number'], request):
        return None
    if (git('rev-parse', payload['head'] + '^{tree}') != payload['tree']
            or git('merge-base', '--is-ancestor', payload['base'], payload['head'], check=False).returncode != 0):
        return None
    review = find_request(request)
    return f'https://cnb.cool/{POLICY["cnb"]}/-/issues/{review["number"]}' if review else None


def forward_pull(issue, pull, base):
    if api(f'{CNB}/issues/{issue["number"]}')['state'] != 'open':
        return
    head = pull['head']['sha']
    branch = 'automation/security-sync-' + hashlib.sha256((base + head).encode()).hexdigest()[:16]
    prior = api(f'{GH}/pulls?state=closed&head={POLICY["github"].split("/")[0]}:{branch}')
    if prior:
        notify_once(issue, branch, 'GitHub对应修复PR已关闭，保持暂停，不重复创建。')
        return
    for target in pages(f'{GH}/pulls?state=open', size_key='per_page'):
        payload = mirror_record(target)
        if not payload or str(payload.get('cnb_number')) != str(pull['number']):
            continue
        if (target['base']['ref'] != 'main' or target['head']['repo']['full_name'] != POLICY['github']):
            continue
        if payload['base'] != base or payload['head'] != head:
            api(f'{GH}/pulls/{target["number"]}', 'PATCH', {'state': 'closed'})
            continue
        if mirror_attestation(target):
            merged = api(f'{GH}/pulls/{target["number"]}/merge', 'PUT', {
                'sha': head, 'merge_method': 'merge',
                'commit_title': 'fix(security): 合并已验证的兼容依赖修复 [skip ci]'})
            if merged and merged.get('merged'):
                after_github_merge(merged.get('sha') or head)
        return
    existing = api(f'{GH}/git/ref/heads/{branch}', missing=True)
    if existing and existing['object']['sha'] != head:
        raise ValueError('Forwarded repair branch was modified')
    if not existing:
        git('push', f'https://github.com/{POLICY["github"]}.git', f'{head}:refs/heads/{branch}')
    payload = {'base': base, 'head': head, 'tree': git('rev-parse', head + '^{tree}'),
               'cnb_number': str(pull['number'])}
    created = api(f'{GH}/pulls', 'POST', {'base': 'main', 'head': branch,
        'title': 'fix(security): 合并已验证的兼容依赖修复',
        'body': f'## 修复与验证\n承接 CNB PR #{pull["number"]}。GitHub是唯一合并入口；'
                '仅固定base/head、文件树、原生CI及双模型证据完全匹配时复用审核，不重新编译APK。\n\n'
                + '<!-- flclash-security-mirror ' + json.dumps(sign(payload)) + ' -->'})
    comment(issue['number'], '修复已送至GitHub合并入口：' + created['html_url'])
    review_reconcile()
    dispatch_workflow('reviews.yaml', 'main')
    ensure_branch_scan(head, branch)


def merge_one():
    base = api(f'{GH}/git/ref/heads/main')['object']['sha']
    pulls = list(pages(f'{CNB}/pulls?state=open'))
    for item in pages(f'{CNB}/issues?state=open'):
        issue = api(f'{CNB}/issues/{item["number"]}')
        payload = record(issue)
        if issue.get('state') != 'open' or not payload or payload.get('group') not in PATHS:
            continue
        for listed in pulls:
            pull = api(f'{CNB}/pulls/{listed["number"]}')
            if (pull['state'] != 'open' or pull.get('is_wip') or pull['head']['repo']['path'] != POLICY['cnb']
                    or pull['base']['ref'] != 'refs/heads/main'
                    or pull['head']['ref'].removeprefix('refs/heads/') != repair_branch(payload)):
                continue
            head = pull['head']['sha']
            git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git', base, head)
            if git('merge-base', '--is-ancestor', head, base, check=False).returncode == 0:
                comment(issue['number'], f'PR #{pull["number"]} 的提交已包含于GitHub主分支 `{base}`，CNB已镜像。关闭验证PR，主任务仍由正式复扫决定。')
                api(f'{CNB}/pulls/{pull["number"]}', 'PATCH', {'state': 'closed'})
                continue
            if not safe_files(base, head, payload['group']):
                forward_pull(issue, pull, base)
                return
            if git('merge-base', '--is-ancestor', base, head, check=False).returncode != 0:
                comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
                comments += list(pages(f'{CNB}/pulls/{pull["number"]}/comments'))
                if active_developer(issue, comments):
                    continue
                merged = git('merge-tree', '--write-tree', base, head, check=False)
                if merged.returncode != 0:
                    notify_once(issue, base + head, '修复分支与主分支有冲突，停止自动刷新。')
                    continue
                refreshed = git('commit-tree', merged.stdout.splitlines()[0], '-p', head, '-p', base,
                                '-m', 'fix(security): 同步已合并的公共修复')
                sync_branch(repair_branch(payload), refreshed)
                return
            request = scope('cnb', pull)
            if request['base'] != base or state(request) != 'success' or not passed_checks(pull['number'], request):
                continue
            if scope('cnb', api(f'{CNB}/pulls/{pull["number"]}')) != request:
                continue
            forward_pull(issue, pull, base)
            return


def push_github(source, branch):
    token = os.environ['GH_TOKEN']
    encoded = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
    env = dict(os.environ, GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
               GIT_CONFIG_VALUE_0='Authorization: Basic ' + encoded, GIT_TERMINAL_PROMPT='0')
    git('push', f'https://github.com/{POLICY["github"]}.git', f'{source}:refs/heads/{branch}', env=env)


def handoff_cnb_main(base, source):
    # CNB moved first. Keep both mains intact and open the GitHub review PR the
    # controller used to refuse by crashing, which also skipped the rescan.
    branch = 'automation/cnb-main-' + source[:12]
    existing = api(f'{GH}/git/ref/heads/{branch}', missing=True)
    if existing and existing['object']['sha'] != source:
        print(f'{branch} points at a different commit; not overwriting it')
        return
    if not existing:
        push_github(source, branch)
    owner = POLICY['github'].split('/')[0]
    if api(f'{GH}/pulls?state=open&head={owner}:{branch}'):
        return
    api(f'{GH}/pulls', 'POST', {
        'base': 'main', 'head': branch,
        'title': 'sync: review CNB main that is ahead of GitHub',
        'body': f'CNB `main` `{source}` is ahead of GitHub `main` `{base}`.\n\n'
                'Required checks must succeed before the controller merges this PR.\n\n'
                f'https://cnb.cool/{POLICY["cnb"]}'})
    review_reconcile()
    dispatch_workflow('reviews.yaml', 'main')
    ensure_branch_scan(source, branch)


def mirror():
    base = api(f'{GH}/git/ref/heads/main')['object']['sha']
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', base)
    git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git', 'refs/heads/main')
    source = git('rev-parse', 'FETCH_HEAD')
    if source != base:
        cnb_contained = git('merge-base', '--is-ancestor', source, base, check=False).returncode == 0
        github_contained = git('merge-base', '--is-ancestor', base, source, check=False).returncode == 0
        if cnb_contained:
            sync_branch('main', base)
        elif github_contained:
            handoff_cnb_main(base, source)
        else:
            print('CNB main and GitHub main diverged; leaving both unchanged')
    ensure_scan(base)
    return False


def dispatch_workflow(name, ref, inputs=None):
    api(f'{GH}/actions/workflows/{name}/dispatches', 'POST', {'ref': ref, 'inputs': inputs or {}})


def ensure_branch_scan(sha, ref):
    runs = api(f'{GH}/actions/workflows/security.yaml/runs?head_sha={sha}&per_page=20')['workflow_runs']
    current = [run for run in runs if run['head_sha'] == sha]
    if any(run['status'] != 'completed' or run['conclusion'] == 'success' for run in current):
        return
    dispatch_workflow('security.yaml', ref, {'scan_only': True})


def after_github_merge(sha):
    if not re.fullmatch(r'[a-f0-9]{40}', sha or ''):
        return
    ensure_scan(sha)
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', sha)
    git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git', 'refs/heads/main')
    cnb = git('rev-parse', 'FETCH_HEAD')
    if cnb == sha:
        return
    if git('merge-base', '--is-ancestor', cnb, sha, check=False).returncode == 0:
        sync_branch('main', sha)
        return
    if git('merge-base', '--is-ancestor', sha, cnb, check=False).returncode != 0:
        print('CNB main and GitHub main diverged; leaving both unchanged')


def merge_ready():
    for listed in pages(f'{GH}/pulls?state=open', size_key='per_page'):
        ref = listed['head']['ref']
        if (listed['head']['repo']['full_name'] != POLICY['github'] or listed['base']['ref'] != 'main'
                or not ref.startswith(('automation/req-', 'automation/cnb-main-', 'automation/security-sync-'))):
            continue
        pull = api(f'{GH}/pulls/{listed["number"]}')
        if pull.get('draft') or pull.get('mergeable_state') != 'clean':
            continue
        sha = pull['head']['sha']
        merged = api(f'{GH}/pulls/{pull["number"]}/merge', 'PUT', {
            'sha': sha, 'merge_method': 'merge'})
        if merged and merged.get('merged'):
            after_github_merge(merged.get('sha') or sha)
            return


def ensure_scan(sha):
    runs = api(f'{GH}/actions/workflows/security.yaml/runs?head_sha={sha}&per_page=100')['workflow_runs']
    current = [run for run in runs if run['head_sha'] == sha]
    if any(run['status'] != 'completed' or run['conclusion'] == 'success' for run in current):
        return
    if len(current) >= 2:
        raise RuntimeError('Security rescan failed twice for current main; manual diagnosis required')
    api(f'{GH}/actions/workflows/security.yaml/dispatches', 'POST', {'ref': 'main'})


def reconcile():
    if POLICY.get('security_auto_merge') is not True:
        return
    if not mirror():
        merge_one()
        merge_ready()


if __name__ == '__main__':
    reconcile()
