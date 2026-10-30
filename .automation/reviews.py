import hashlib
import json
import os
import re
import sys
import time

from control import CI_GRACE, CNB, GH, POLICY, all_issues, api, check_name, comment, pages, sign, verify
from review_evidence import describe

CONTEXT = 'FlClash/paired-review'
ROLES = ('审查助手', 'GLM复核助手')
# The main.pull_request pipelines in .cnb.yml, and the only checks that gate a review.
CI_PIPELINES = ('Dependency vulnerability gate', 'Automation unit tests', 'Go dependency regression tests',
                'Flutter and Android requirement tests', 'Rust dependency regression tests', 'Paired review gate')
CI_GRACE_SECONDS = 80 * 60


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


def role_reports(request, issue, comments):
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
            latest[role] = 'malformed'
            continue
        try:
            report = json.loads(matches[-1])
        except ValueError:
            latest[role] = 'malformed'
            continue
        if report.get('request') != identity(request):
            continue
        latest[role] = ('pass' if report.get('verdict') == 'pass'
                        and report.get('blockers') == 0 else 'block')
    return latest


def result(request, issue, comments):
    if issue['state'] != 'open':
        return 'failure'
    latest = role_reports(request, issue, comments)
    if any(value in ('block', 'malformed') for value in latest.values()):
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


def requirement_brief(pull):
    ref = str((pull.get('head') or {}).get('ref', '')).removeprefix('refs/heads/')
    match = re.fullmatch(r'automation/req-(\d+)', ref)
    if not match:
        return ''
    # Imported lazily: requirements imports this module at load time.
    from requirements import owner, parse
    issue = api(f'{CNB}/issues/{match[1]}', missing=True)
    if not issue or not owner(issue):
        return ''
    acceptance = parse(issue.get('body', ''))['acceptance']
    if not acceptance:
        return ''
    return (f'本 PR 实现需求 #{match[1]}：https://cnb.cool/{POLICY["cnb"]}/-/issues/{match[1]}\n'
            '逐条核对下列验收标准。任何一条不能从实际 diff 确认已满足，或开发助手在该需求 issue '
            '最新的阶段报告里写明未满足、未完成，都必须判 block，并在阻断项里写明是哪一条。'
            'CI 通过不等于验收通过。\n' + acceptance + '\n\n')


def ensure_request(request, title, brief=''):
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
    body = (f'PR 自动结对审核：{url}\n\n{marker}\n\n' + brief + describe(request) + '\n'
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
    notice = (f'\n<!-- flclash-review-notice {number} -->' if platform == 'cnb' else '')
    issue = api(f'{CNB}/issues', 'POST', {'title': display_title,
                'body': body, 'work_mode': False, 'assignees': [POLICY['approver']]})
    body = (f'结对审核： https://cnb.cool/{POLICY["cnb"]}/-/issues/{issue["number"]}\n'
            f'base `{request["base"]}` / head `{request["head"]}`。两位审核者完成且无阻断问题后检查才通过。'
            + notice)
    if platform == 'github':
        api(f'{GH}/issues/{number}/comments', 'POST', {'body': body})
    else:
        comment(number, body)
    return issue


def _checkpoint(request, role, kind):
    payload = {'request': identity(request), 'role': role, 'kind': kind}
    return '<!-- flclash-review-reconsider ' + json.dumps(sign(payload)) + ' -->'


def _owner_comment(comments, marker):
    return next((c for c in comments if c.get('author', {}).get('username') == POLICY['approver']
                 and c.get('author', {}).get('is_npc') is False and marker in c.get('body', '')), None)


def reconsider(request, issue, comments):
    from npc_recovery import latest_attempts
    latest = role_reports(request, issue, comments)
    attempts = latest_attempts(issue, comments)
    for role, status in latest.items():
        if status not in ('block', 'malformed'):
            continue
        other = next(r for r in ROLES if r != role)
        if status == 'block' and latest.get(other) != 'pass':
            continue
        attempt = attempts.get(role)
        if attempt and api(f'{CNB}/build/status/{attempt[1]["sn"]}')['status'] not in ('success', 'error', 'failure'):
            continue
        sample = json.dumps({'request': identity(request), 'verdict': 'pass', 'blockers': 0})
        reconsidered = _owner_comment(comments, _checkpoint(request, role, 'reconsider'))
        if reconsidered:
            answered = any(c.get('author', {}).get('username') == f'{POLICY["cnb"]}({role})'
                           and c.get('created_at', '') > reconsidered.get('created_at', '') for c in comments)
            if (status != 'malformed' or not answered
                    or _owner_comment(comments, _checkpoint(request, role, 'verdict'))):
                continue
            # The bounded recheck still omitted the machine line; only ask it to restate its own conclusion.
            body = (_checkpoint(request, role, 'verdict') + '\n\n'
                    + f'@{POLICY["cnb"]}({role}) 你在本 Issue 最新的报告缺少机器结论行，门禁无法读取。'
                    '不要重新审核，也不要调用工具；只根据你自己那份报告的结论回复一行机器结论。'
                    '报告里有未解决的阻断、未验证的验收标准或无法确认的项时必须用 block：\n'
                    + 'FLCLASH_REVIEW ' + sample)
            api(f'{CNB}/issues/{issue["number"]}/comments', 'POST', {'body': body, 'work_mode': False})
            continue
        marker = _checkpoint(request, role, 'reconsider')
        body = (marker + '\n\n' + describe(request)
                + f'@{POLICY["cnb"]}({role}) 报告格式不完整或双方结论有分歧，执行唯一一次有界复核。'
                '最多8次工具调用；只核对实际差异和现有阻断，明确纠正已证实的事实错误。'
                '不为了达成共识而通过；真实阻断保留，不能确认则报告block。'
                '不等待另一位、不自行召唤。报告最后单独一行输出机器结论（无阻断时才使用下例）：\n'
                + 'FLCLASH_REVIEW ' + sample)
        api(f'{CNB}/issues/{issue["number"]}/comments', 'POST', {'body': body, 'work_mode': False})


def _number(item):
    return str(item['number'])


def _since(stamp):
    import datetime
    return time.time() - datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()


def existing_review(pull):
    """Return the review issue already opened for this base/head without listing every issue."""
    request = scope('cnb', pull)
    for summary in pages(f'{CNB}/pulls/{pull["number"]}/comments', size_key='page_size'):
        if '<!-- flclash-review-notice ' not in str(summary.get('body', '')):
            continue
        detail = api(f'{CNB}/issues/{summary["number"]}', missing=True)
        if detail and request_from(detail) == request:
            return detail
    return None


def ci_state(checks):
    """Return pending, failure or success over the six pull_request pipelines only."""
    from wake import SETTLED
    named = {}
    for item in (checks or {}).get('statuses') or []:
        named.setdefault(check_name(item), []).append(item.get('state'))
    if any(name not in named for name in CI_PIPELINES):
        return 'pending'
    settled = {name: all(found in SETTLED for found in named[name]) for name in CI_PIPELINES}
    if not all(settled.values()):
        return 'pending'
    return 'success' if all(found == 'success' for name in CI_PIPELINES for found in named[name]) else 'failure'


def ci_hold(pull):
    """Return (pending, waited) for a requirement or security PR whose review must wait for CI."""
    if not re.fullmatch(r'(automation/req-|security/group-).+', pull['head']['ref'].removeprefix('refs/heads/')):
        return False, False
    if existing_review(pull):
        return False, False
    checks = api(f'{CNB}/pulls/{pull["number"]}/commit-statuses')
    state = ci_state(checks)
    if state == 'failure':
        print(f'cnb PR #{_number(pull)}: CI failed, review deferred')
        return True, False
    if state == 'success':
        return False, False
    stamps = [item.get('created_at') for item in (checks or {}).get('statuses') or [] if item.get('created_at')]
    if stamps and _since(min(stamps)) < CI_GRACE_SECONDS:
        print(f'cnb PR #{_number(pull)}: waiting for CI')
        return True, False
    print(f'cnb PR #{_number(pull)}: CI unsettled after 80m, review opened')
    return False, True


def unsettled_brief(pull):
    """Name the pipelines a review opened past the grace could not wait for."""
    states = {}
    from wake import SETTLED
    statuses = (api(f'{CNB}/pulls/{pull["number"]}/commit-statuses') or {}).get('statuses') or []
    for item in statuses:
        states.setdefault(check_name(item), []).append(item['state'])
    open_names = [name for name in CI_PIPELINES
                  if any(found not in SETTLED for found in states.get(name, ['pending']))]
    return (f'CI 未结束就开审的流水线：{", ".join(open_names)}。这些条目按未验证处理，'
            '不能因为 CI 没跑完就通过。\n\n')


def withhold(pull):
    """Keep a review that was opened before CI settled from turning green until the pipelines finish."""
    if not re.fullmatch(r'automation/req-.+', pull['head']['ref'].removeprefix('refs/heads/')):
        return
    statuses = (api(f'{CNB}/pulls/{pull["number"]}/commit-statuses') or {}).get('statuses') or []
    if ci_state({'statuses': statuses}) not in ('pending', 'failure'):
        api(f'{CNB}/statuses/{pull["head"]["sha"]}', 'POST', {
            'state': 'failure', 'context': CI_GRACE,
            'description': 'Review opened before CI settled; merge waits for every pipeline'})
    elif any(item.get('context') == CI_GRACE for item in statuses):
        api(f'{CNB}/statuses/{pull["head"]["sha"]}', 'POST', {
            'state': 'success', 'context': CI_GRACE, 'description': 'Every pull_request pipeline has settled'})


def reconcile():
    close_finished_reviews()
    github_results = {}
    for platform in ('github', 'cnb'):
        for pull in pages(f'{endpoint(platform)}/pulls?state=open', size_key='per_page' if platform == 'github' else 'page_size'):
            pull = api(f'{endpoint(platform)}/pulls/{pull["number"]}')
            request = scope(platform, pull)
            waiting, late = (False, False) if platform == 'github' else ci_hold(pull)
            if waiting:
                continue
            if platform == 'github':
                from security_finish import mirror_attestation, mirror_record
                attestation = mirror_attestation(pull)
                if attestation:
                    github_results.setdefault(request['head'], []).append(('success', attestation))
                    print(f'GitHub PR #{request["number"]}: verified identical-tree CNB review and CI attestation')
                    continue
                forwarded = mirror_record(pull)
                if forwarded and 'cnb_number' in forwarded:
                    url = f'https://cnb.cool/{POLICY["cnb"]}/-/pulls/{forwarded["cnb_number"]}'
                    github_results.setdefault(request['head'], []).append(('pending', url))
                    continue
            issue = ensure_request(request, pull['title'],
                                   (unsettled_brief(pull) if late else '') + requirement_brief(pull))
            withhold(pull)
            comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
            status = result(request, issue, comments)
            if issue['state'] == 'open':
                reconsider(request, issue, comments)
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
        time.sleep(30)
    raise ValueError('Paired review timed out; rerun after both reports pass')


if __name__ == '__main__':
    {'reconcile': reconcile, 'cnb-gate': cnb_gate}[sys.argv[1]]()
