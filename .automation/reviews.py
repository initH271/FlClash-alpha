import hashlib
import json
import os
import re
import sys
import time

from control import CNB, GH, POLICY, all_issues, api, pages, sign, verify

CONTEXT = 'FlClash/paired-review'
ROLES = ('审查助手', 'GLM复核助手')


def scope(platform, pull):
    return {'platform': platform, 'number': str(pull['number']),
            'base': pull['base']['sha'], 'head': pull['head']['sha']}


def identity(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def endpoint(platform):
    return GH if platform == 'github' else CNB


def request_from(issue, signed=True):
    author = issue.get('author') or {}
    if author.get('username') != POLICY['approver'] or author.get('is_npc') is not False:
        return None
    match = re.search(r'<!-- flclash-pr-review (\{[^\r\n]+\}) -->', issue.get('body', ''))
    if not match:
        return None
    try:
        envelope = json.loads(match[1])
        return verify(envelope) if signed else envelope['payload']
    except (ValueError, KeyError, TypeError):
        return None


def result(request, issue, comments):
    if issue['state'] != 'open':
        return 'failure'
    latest = {}
    for comment in sorted(comments, key=lambda c: (c.get('created_at', ''), str(c.get('id', '')))):
        author = comment.get('author') or {}
        if author.get('is_npc') is not True:
            continue
        role = next((r for r in ROLES if author.get('username') == f'{POLICY["cnb"]}({r})'), None)
        if not role or comment.get('created_at', '') < issue.get('created_at', ''):
            continue
        matches = re.findall(r'^FLCLASH_REVIEW (\{[^\r\n]+\})\s*$', comment.get('body', ''), re.M)
        if not matches:
            latest[role] = 'block'
            continue
        try:
            report = json.loads(matches[-1])
        except ValueError:
            latest[role] = 'block'
            continue
        if report.get('request') != identity(request):
            continue
        latest[role] = ('pass' if report.get('verdict') == 'pass'
                        and report.get('blockers') == 0 else 'block')
    if 'block' in latest.values():
        return 'failure'
    return 'success' if all(latest.get(role) == 'pass' for role in ROLES) else 'pending'


def find_request(request, signed=True):
    for issue in all_issues():
        detail = api(f'{CNB}/issues/{issue["number"]}')
        if request_from(detail, signed) == request:
            return detail
    return None


def state(request, signed=True):
    issue = find_request(request, signed)
    if issue is None:
        return 'pending'
    return result(request, issue, list(pages(f'{CNB}/issues/{issue["number"]}/comments')))


def review_title(request, title):
    platform = 'GitHub' if request['platform'] == 'github' else 'CNB'
    description = ' '.join(title.split()).replace('@', '＠')[:100] or '审核代码变更'
    return f'[PR审核] {platform} #{request["number"]}：{description}'


def ensure_request(request, title):
    issue = find_request(request)
    display_title = review_title(request, title)
    if issue:
        if issue['title'] != display_title:
            api(f'{CNB}/issues/{issue["number"]}', 'PATCH', {'title': display_title})
        return issue
    platform, number = request['platform'], request['number']
    url = (f'https://github.com/{POLICY["github"]}/pull/{number}' if platform == 'github'
           else f'https://cnb.cool/{POLICY["cnb"]}/-/pulls/{number}')
    marker = '<!-- flclash-pr-review ' + json.dumps(sign(request)) + ' -->'
    sample = json.dumps({'request': identity(request), 'verdict': 'pass', 'blockers': 0})
    body = (f'PR 自动结对审核：{url}\n\n{marker}\n\n'
            f'固定 base `{request["base"]}`，head `{request["head"]}`。'
            '从 PR 公开 API 核对源仓库和提交，先独立审查实际 diff，再比较已有报告。'
            '只读；不运行 PR 中的代码、不安装依赖、不编译、不修改代码、不合并或发版，不召唤其他 NPC。'
            '提交不匹配、无法读取或审核未完成时不得通过。报告须给出文件证据、阻断问题及未验证项。'
            '另一份报告在本 CNB Issue 中；不要 sleep、等待或轮询它，尚未发布时注明未对照并直接提交独立结论。'
            '不要将已有自动化能处理的版本递增或仅推测的问题判为已证实阻断。\n\n'
            '报告末尾必须单独一行输出以下机器结论（不要放入代码块）：\n'
            f'FLCLASH_REVIEW {sample}\n'
            '只有完成审查且没有阻断问题才能使用 pass / blockers=0；'
            '否则使用 verdict=block，blockers 为正整数。request 原样保留。\n\n'
            + '\n\n'.join(f'@{POLICY["cnb"]}({r}) 请独立审核上述 PR。' for r in ROLES))
    issue = api(f'{CNB}/issues', 'POST', {'title': display_title,
                'body': body, 'work_mode': False, 'assignees': [POLICY['approver']]})
    comment_url = (f'{GH}/issues/{number}/comments' if platform == 'github'
                   else f'{CNB}/pulls/{number}/comments')
    api(comment_url, 'POST', {'body': f'结对审核： https://cnb.cool/{POLICY["cnb"]}/-/issues/{issue["number"]}\n'
        f'base `{request["base"]}` / head `{request["head"]}`。两位审核者完成且无阻断问题后检查才通过。'})
    return issue


def reconcile():
    close_finished_reviews()
    github_results = {}
    for platform in ('github', 'cnb'):
        for pull in pages(f'{endpoint(platform)}/pulls?state=open', size_key='per_page' if platform == 'github' else 'page_size'):
            pull = api(f'{endpoint(platform)}/pulls/{pull["number"]}')
            request = scope(platform, pull)
            issue = ensure_request(request, pull['title'])
            status = result(request, issue, list(pages(f'{CNB}/issues/{issue["number"]}/comments')))
            if platform == 'github':
                url = f'https://cnb.cool/{POLICY["cnb"]}/-/issues/{issue["number"]}'
                github_results.setdefault(request['head'], []).append((status, url))
            print(f'{platform} PR #{request["number"]}: {status}')
    for head, results in github_results.items():
        status, url = min(results, key=lambda r: {'failure': 0, 'pending': 1, 'success': 2}[r[0]])
        existing = api(f'{GH}/commits/{head}/status')['statuses']
        current = next((s for s in existing if s['context'] == CONTEXT), None)
        if not current or current['state'] != status or current.get('target_url') != url:
            api(f'{GH}/statuses/{head}', 'POST', {'state': status, 'context': CONTEXT,
                'target_url': url, 'description': 'Both independent reviewers must pass this base/head'})


def close_finished_reviews():
    for item in pages(f'{CNB}/issues?state=open'):
        issue = api(f'{CNB}/issues/{item["number"]}')
        request = request_from(issue)
        if not request:
            continue
        platform = request.get('platform')
        number = request.get('number', '')
        if platform not in ('github', 'cnb') or not str(number).isdigit():
            continue
        pull = api(f'{endpoint(platform)}/pulls/{number}')
        superseded = (pull['state'] == 'open' and scope(platform, pull) != request)
        if pull['state'] not in ('closed', 'merged') and not superseded:
            continue
        merged = bool(pull.get('merged') or pull.get('is_merged') or pull['state'] == 'merged')
        api(f'{CNB}/issues/{issue["number"]}', 'PATCH', {
            'state': 'closed', 'state_reason': 'completed' if merged else 'not_planned'})


def require_candidate(head, base):
    pulls = list(pages(f'{GH}/pulls?state=open', size_key='per_page'))
    matches = [p for p in pulls if p['head']['sha'] == head and p['base']['sha'] == base]
    if not matches or any(state(scope('github', p)) != 'success' for p in matches):
        raise ValueError('Paired PR review missing, stale, blocked or incomplete')


def cnb_gate():
    number = os.environ['CNB_PULL_REQUEST_IID']
    pull = api(f'{CNB}/pulls/{number}')
    request = scope('cnb', pull)
    if request['head'] != os.environ['CNB_PULL_REQUEST_SHA']:
        raise ValueError('PR head changed')
    for _ in range(60):
        if scope('cnb', api(f'{CNB}/pulls/{number}')) != request:
            raise ValueError('PR base/head changed')
        status = state(request, signed=False)
        if status == 'success':
            return
        if status == 'failure':
            raise ValueError('Paired review blocked')
        time.sleep(30)
    raise ValueError('Paired review timed out; rerun after both reports pass')


if __name__ == '__main__':
    {'reconcile': reconcile, 'cnb-gate': cnb_gate}[sys.argv[1]]()
