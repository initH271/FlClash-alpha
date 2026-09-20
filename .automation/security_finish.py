import hashlib
import json
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


def merge_one():
    for item in pages(f'{CNB}/issues?state=open'):
        issue = api(f'{CNB}/issues/{item["number"]}')
        payload = record(issue)
        if not payload or payload.get('group') not in PATHS:
            continue
        for listed in pages(f'{CNB}/pulls?state=open'):
            pull = api(f'{CNB}/pulls/{listed["number"]}')
            if (pull.get('is_wip') or pull['head']['repo']['path'] != POLICY['cnb']
                    or pull['base']['ref'] != 'refs/heads/main'
                    or pull['head']['ref'].removeprefix('refs/heads/') != repair_branch(payload)):
                continue
            request = scope('cnb', pull)
            git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git', request['base'], request['head'])
            if git('merge-base', '--is-ancestor', request['base'], request['head'], check=False).returncode != 0:
                comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
                comments += list(pages(f'{CNB}/pulls/{pull["number"]}/comments'))
                if active_developer(issue, comments) or not safe_files(request['base'], request['head'], payload['group']):
                    continue
                merged = git('merge-tree', '--write-tree', request['base'], request['head'], check=False)
                if merged.returncode != 0:
                    notify_once(issue, request['head'] + request['base'], '安全修复分支与最新主分支有冲突，停止自动更新，需处理冲突。')
                    continue
                head = git('commit-tree', merged.stdout.splitlines()[0], '-p', request['head'], '-p', request['base'],
                           '-m', 'fix(security): 同步已合并的公共修复')
                sync_branch(repair_branch(payload), head)
                return
            if state(request) != 'success' or not passed_checks(pull['number'], request):
                continue
            git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git', request['base'], request['head'])
            if not safe_files(request['base'], request['head'], payload['group']):
                notify_once(issue, request['head'], f'PR #{pull["number"]} 检查通过，但不满足兼容依赖自动合并边界'
                            '（仅锁文件/版本变更、无工具链变化、无主版本或0.x次版本跨越）。需明确评估后人工合并，未绕过检查。')
                continue
            current = api(f'{CNB}/pulls/{pull["number"]}')
            if scope('cnb', current) != request or current['state'] != 'open':
                continue
            failed_marker = '<!-- security-merge-failed ' + request['head'] + ' -->'
            comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
            if any(c.get('author', {}).get('username') == POLICY['approver']
                   and c.get('author', {}).get('is_npc') is False and failed_marker in c.get('body', '') for c in comments):
                continue
            try:
                api(f'{CNB}/pulls/{pull["number"]}/reviews', 'POST', {
                    'event': 'approve', 'body': '限定依赖文件、兼容版本、当前提交双模型与全部检查通过；控制器按授权批准，禁止强制合并。'})
                current = api(f'{CNB}/pulls/{pull["number"]}')
                if scope('cnb', current) != request or not passed_checks(pull['number'], request):
                    continue
                merged = api(f'{CNB}/pulls/{pull["number"]}/merge', 'PUT', {
                    'merge_style': 'merge', 'force': False,
                    'commit_title': 'fix(security): 合并已验证的兼容依赖修复 [skip ci]'})
            except RuntimeError:
                comment(issue['number'], failed_marker + '\n\n自动批准/合并接口未成功确认，已停止此提交的重复写入。'
                        '请检查控制器失败日志、令牌PR/评审权限及平台实际合并状态；未强制合并。')
                raise
            if merged.get('merged'):
                comment(issue['number'], f'兼容依赖修复 PR #{pull["number"]} 已通过全部门禁并自动合并，等待双仓同步及正式复扫。')
                return


def mirror_record(pull):
    match = re.search(r'<!-- flclash-security-mirror (\{[^\r\n]+\}) -->', pull.get('body', ''))
    if not match:
        return None
    try:
        return verify(json.loads(match[1]))
    except (ValueError, KeyError, TypeError):
        return None


def tested_source(source):
    parents = git('rev-list', '--parents', '-n', '1', source).split()[1:]
    if len(parents) != 2:
        return False
    for pull in pages(f'{CNB}/pulls?state=all'):
        if not pull.get('is_merged') or pull['base']['sha'] != parents[0] or pull['head']['sha'] != parents[1]:
            continue
        request = scope('cnb', pull)
        review = find_request(request)
        if not review or (review['state'] != 'open' and review.get('state_reason') != 'completed'):
            return False
        reports = list(pages(f'{CNB}/issues/{review["number"]}/comments'))
        if result(request, dict(review, state='open'), reports) == 'success' and passed_checks(pull['number'], request):
            return review
        return None
    return False


def mirror_attestation(pull):
    payload = mirror_record(pull)
    if not payload:
        return None
    expected = 'automation/security-sync-' + hashlib.sha256((payload['base'] + payload['source']).encode()).hexdigest()[:16]
    if (pull['base']['ref'] != 'main' or pull['head']['repo']['full_name'] != POLICY['github']
            or pull['head']['ref'] != expected or pull['base']['sha'] != payload['base']
            or pull['head']['sha'] != payload['head']):
        return None
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', payload['head'])
    parents = git('rev-list', '--parents', '-n', '1', payload['source']).split()[1:]
    if len(parents) != 2:
        return None
    if (git('rev-parse', payload['base'] + '^{tree}') != git('rev-parse', parents[0] + '^{tree}')
            or git('rev-parse', payload['head'] + '^{tree}') != payload['tree']
            or payload['tree'] != git('rev-parse', payload['source'] + '^{tree}')):
        return None
    if not safe_files(payload['base'], payload['head']):
        return None
    review = tested_source(payload['source'])
    return f'https://cnb.cool/{POLICY["cnb"]}/-/issues/{review["number"]}' if review else None


def mirror():
    base = api(f'{GH}/git/ref/heads/main')['object']['sha']
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', base)
    git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git', 'refs/heads/main')
    source = git('rev-parse', 'FETCH_HEAD')
    if source == base:
        ensure_scan(base)
        return False
    if git('merge-base', '--is-ancestor', source, base, check=False).returncode == 0:
        sync_branch('main', base)
        ensure_scan(base)
        return True
    if not safe_files(base, source) or not tested_source(source):
        for listed in pages(f'{CNB}/issues?state=open'):
            issue = api(f'{CNB}/issues/{listed["number"]}')
            if record(issue):
                notify_once(issue, base + source, '双仓主分支存在差异，但不满足兼容依赖与原始CI证据复用条件。'
                            '自动同步暂停，需审核范围外变更或补齐测试证据；不会强推或绕过保护。')
        return True
    for pull in pages(f'{GH}/pulls?state=open', size_key='per_page'):
        payload = mirror_record(pull)
        if not payload:
            continue
        expected_branch = 'automation/security-sync-' + hashlib.sha256((payload['base'] + payload['source']).encode()).hexdigest()[:16]
        if (pull['base']['ref'] != 'main' or pull['head']['repo']['full_name'] != POLICY['github']
                or pull['head']['ref'] != expected_branch):
            continue
        if payload['base'] != base or payload['source'] != source:
            api(f'{GH}/pulls/{pull["number"]}', 'PATCH', {'state': 'closed'})
            continue
        git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', payload['head'])
        if (pull['head']['sha'] != payload['head'] or pull['base']['sha'] != base
                or git('rev-parse', payload['head'] + '^{tree}') != payload['tree']):
            raise ValueError('Signed security mirror changed')
        if mirror_attestation(pull) or state(scope('github', pull)) == 'success':
            api(f'{GH}/pulls/{pull["number"]}/merge', 'PUT', {
                'sha': payload['head'], 'merge_method': 'merge',
                'commit_title': 'fix(security): 同步已审核的依赖修复 [skip ci]'})
        return True
    tree = git('merge-tree', '--write-tree', base, source).splitlines()[0]
    branch = 'automation/security-sync-' + hashlib.sha256((base + source).encode()).hexdigest()[:16]
    prior = api(f'{GH}/pulls?state=closed&head={POLICY["github"].split("/")[0]}:{branch}')
    if prior:
        return True
    existing = api(f'{GH}/git/ref/heads/{branch}', missing=True)
    if existing:
        head = existing['object']['sha']
        git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', head)
        if git('rev-parse', head + '^{tree}') != tree or git('rev-list', '--parents', '-n', '1', head).split()[1:] != [base, source]:
            raise ValueError('Mirror branch was modified')
    else:
        head = git('commit-tree', tree, '-p', base, '-p', source, '-m', 'fix(security): 汇合依赖修复 [skip ci]')
        git('push', 'origin', f'{head}:refs/heads/{branch}')
    payload = {'base': base, 'source': source, 'head': head, 'tree': tree}
    api(f'{GH}/pulls', 'POST', {'base': 'main', 'head': branch,
        'title': 'fix(security): 同步已验证的兼容依赖修复',
        'body': '同步 CNB 已合并的兼容依赖文件。仅当两侧基线与结果文件树完全相同、签名记录及原双模型/CI证据有效时复用审核，否则重新审核。不重新编译 APK。\n\n'
                + '<!-- flclash-security-mirror ' + json.dumps(sign(payload)) + ' -->'})
    review_reconcile()
    return True


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


if __name__ == '__main__':
    reconcile()
