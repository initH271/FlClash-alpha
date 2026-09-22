import hashlib
import json
import re

from control import CNB, GH, POLICY, api, comment, git, pages, sign, verify
from reviews import find_request, reconcile as review_reconcile, scope, state
from security_finish import ensure_branch_scan, push_github

HEADINGS = ('要改什么', '验收标准', '不做什么', '影响范围', '允许改自动化配置', '相关文件或界面')
REQUIRED = ('要改什么', '验收标准', '不做什么', '影响范围')
PLACEHOLDERS = {
    '要改什么': '一句话说清要改的行为',
    '验收标准': '完成后可以核对的条件，每行一条',
    '不做什么': '不发 APK、不改 main',
}
RUNGS = (60, 120, 240)
TERMINAL = {'success', 'error', 'failure', 'cancel', 'cancelled'}
ROLES = ('开发助手', '审查助手')
QUOTA = ('额度', '配额', '余额不足')


def owner(issue):
    author = issue.get('author') or {}
    return author.get('username') == POLICY['approver'] and author.get('is_npc') is False


def sections(body):
    found = {}
    current = None
    for line in body.splitlines():
        match = re.fullmatch(r'##\s+(.+?)\s*', line.strip())
        if match and match[1] in HEADINGS:
            current = match[1]
            found[current] = []
            continue
        if current:
            found[current].append(line)
    return {name: '\n'.join(lines).strip() for name, lines in found.items()}


def parse(body):
    parts = sections(body)
    missing = []
    for name in REQUIRED:
        text = parts.get(name, '')
        if not text or text == PLACEHOLDERS.get(name):
            missing.append(name)
    areas = parts.get('影响范围', '')
    allowed = bool(re.search(r'\[(?i:x)\]', parts.get('允许改自动化配置', '')))
    if '自动化配置' in areas and not allowed and '允许改自动化配置' not in missing:
        missing.append('允许改自动化配置')
    acceptance = parts.get('验收标准', '')
    return {'missing': missing, 'acceptance': acceptance, 'goal': parts.get('要改什么', ''),
            'limits': parts.get('不做什么', ''), 'areas': areas, 'allowed': allowed,
            'files': parts.get('相关文件或界面', ''),
            'scope': hashlib.sha256(acceptance.encode()).hexdigest()[:16]}


def markers(comments):
    found = []
    for item in comments:
        match = re.search(r'<!-- flclash-requirement (\{[^\r\n]+\}) -->', item.get('body', ''))
        if not match:
            continue
        try:
            data = dict(verify(json.loads(match[1])))
        except (ValueError, KeyError, TypeError):
            continue
        data['at'] = item.get('created_at', '')
        found.append(data)
    return sorted(found, key=lambda item: item['at'])


def attempts(items):
    found = []
    for item in items:
        for entry in (item.get('statuses') or {}).get('npc', []):
            context = entry.get('context') or {}
            states = entry.get('statuses') or []
            if context.get('npc.slug') != POLICY['cnb'] or not states:
                continue
            last = states[-1]
            found.append({'at': item.get('created_at', ''), 'state': last.get('state', ''),
                          'detail': last.get('description', ''), 'sn': context.get('sn', ''),
                          'role': context.get('npc.name', '')})
    return found


def quota(text):
    return any(word in (text or '') for word in QUOTA)


def next_rung(current):
    if current not in RUNGS or current == RUNGS[-1]:
        return RUNGS[-1]
    return RUNGS[RUNGS.index(current) + 1]


def running(rows):
    return any(row['state'] not in TERMINAL and row['role'] in ROLES for row in rows)


def after(rows, stamp, role):
    return [row for row in rows if row['at'] >= stamp and row['role'] == role]


def reported(comments, stamp, role):
    name = f'{POLICY["cnb"]}({role})'
    for item in comments:
        author = item.get('author') or {}
        if item.get('created_at', '') < stamp or author.get('is_npc') is not True:
            continue
        if author.get('username') != name:
            continue
        body = item.get('body', '').strip()
        if body and body.casefold() != 'ok':
            return body
    return ''


def envelope(payload):
    return '<!-- flclash-requirement ' + json.dumps(sign(payload)) + ' -->'


def instruction(parsed, rung, phase, tree, log, note, previous):
    reserve = max(1, rung * 3 // 4)
    lines = [
        f'本轮只用 {rung} 轮。约第 {reserve} 轮起停止扩大调查。',
        '把已改文件提交到指定分支，允许提交尚未完成的进度。',
        '阶段评论必须写提交 SHA、已核实的事实、已改文件、未完成项。还没改到文件时也要写这四项。',
        '环境里已有 Flutter、Go 和 Android SDK。不要现装这些工具。',
        '不推 main，不合并，不发版。和 main 冲突时拉取后合并，不强推。',
    ]
    if parsed['allowed']:
        lines.append('本轮允许 PR 修改 .automation/、.cnb/、.github/。')
    else:
        lines.append('不要修改 .automation/、.cnb/、.github/。必须改这些路径时，在阶段评论写明跳过了什么，并继续其余部分。')
    lines.append(f'要改什么：{parsed["goal"]}')
    lines.append(f'验收标准：{parsed["acceptance"]}')
    lines.append(f'不做什么：{parsed["limits"]}')
    if parsed['files']:
        lines.append(f'相关文件或界面：{parsed["files"]}')
    if tree:
        lines.append(f'从已有提交 `{tree}` 继续，先 git fetch。已核实的事实不要重头搜索。')
    if previous:
        lines.append('上一轮阶段评论：\n' + previous[:1500])
    if log:
        lines.append(f'上一轮没有留下可用进度。先读构建日志：{log}')
    if note:
        lines.append(note)
    if phase == 'diagnose':
        lines = [
            '只读。对照验收标准、上一档阶段评论和分支 diff。',
            '只写一件事：下一个具体改动（文件和改什么），或指出哪条验收标准在仓库里做不到。',
            '不改代码，不推分支，不合并，不发版，不召唤其他 NPC。最多 60 轮。',
            f'验收标准：{parsed["acceptance"]}',
        ]
    return '\n'.join(lines)


def dispatch_action(parsed, phase, rung, tree, log, note, previous, role):
    return {'kind': 'dispatch', 'phase': phase, 'rung': rung, 'tree': tree or '',
            'role': role, 'work_mode': role == '开发助手',
            'instruction': instruction(parsed, rung, phase, tree, log, note, previous)}


def decide(issue, comments, rows, tree, contained, checks_green, review_failed, review_text, now):
    parsed = parse(issue.get('body', ''))
    known = [item for item in markers(comments) if item.get('issue') == str(issue['number'])]
    form = [item for item in known if item.get('phase') == 'invalid']
    if parsed['missing']:
        if form:
            return {'kind': 'wait'}
        return {'kind': 'note', 'phase': 'invalid', 'rung': 0, 'tree': '',
                'body': '需求表单不完整，未派开发助手。缺：' + '、'.join(parsed['missing'])}
    if contained:
        return {'kind': 'close'}
    scoped = [item for item in known if item.get('scope') == parsed['scope'] and item.get('phase') != 'invalid']
    if any(item.get('phase') == 'quota' for item in scoped):
        return {'kind': 'wait'}
    if any(item.get('phase') == 'stuck' for item in scoped):
        return {'kind': 'wait'}
    if running(rows):
        return {'kind': 'wait'}
    if checks_green:
        return {'kind': 'forward'}
    last = scoped[-1] if scoped else None
    if last and quota(last.get('detail', '')):
        return {'kind': 'wait'}
    later = after(rows, last['at'] if last else '', '开发助手') if last else []
    review_rows = after(rows, last['at'], '审查助手') if last else []
    if later and quota(later[-1]['detail']):
        return {'kind': 'stop', 'phase': 'quota', 'rung': last['rung'], 'tree': tree or '',
                'body': '账户额度用尽，不再加轮次。' + later[-1]['detail'][:300]}
    if not last:
        return dispatch_action(parsed, 'dev', RUNGS[0], tree, '', '', '', '开发助手')
    if not later and not review_rows:
        age = now - _stamp(last['at'])
        if age.total_seconds() > 1800:
            return dispatch_action(parsed, last['phase'], last['rung'], tree, '', '上次派发没有回执，按原档重派。', '', 
                                   '审查助手' if last['phase'] == 'diagnose' else '开发助手')
        return {'kind': 'wait'}
    if last['phase'] == 'diagnose':
        text = reported(comments, last['at'], '审查助手')
        if not review_rows or review_rows[-1]['state'] not in TERMINAL:
            return {'kind': 'wait'}
        if not text:
            return {'kind': 'stop', 'phase': 'stuck', 'rung': last['rung'], 'tree': tree or '',
                    'body': f'审查没有留下结论，tree `{tree or "无"}` 未变，停止加轮次。'}
        return dispatch_action(parsed, 'targeted', last['rung'], tree, '', text, '', '开发助手')
    if last['phase'] == 'targeted' and (not tree or tree == last.get('tree')):
        if not later or later[-1]['state'] not in TERMINAL:
            return {'kind': 'wait'}
        return {'kind': 'stop', 'phase': 'stuck', 'rung': last['rung'], 'tree': tree or '',
                'body': f'换了做法之后 tree `{tree or "无"}` 仍未变化，停止加轮次。'}
    current = later[-1] if later else None
    if current and current['state'] not in TERMINAL:
        return {'kind': 'wait'}
    progressed = bool(tree) and tree != (last.get('tree') or '')
    if review_failed and not (last['phase'] == 'targeted' and last.get('tree') == tree):
        return dispatch_action(parsed, 'targeted', next_rung(last['rung']), tree, '', review_text,
                               reported(comments, last['at'], '开发助手'), '开发助手')
    if current and not re.fullmatch(r'cnb-[a-z0-9-]+', current['sn'] or ''):
        return dispatch_action(parsed, 'retry', last['rung'], tree, '', '上次构建号异常，按原档续跑。', '', '开发助手')
    if progressed:
        note = '先读失败日志，改完推同一分支。' if review_failed else ''
        return dispatch_action(parsed, 'dev', next_rung(last['rung']), tree, '', note,
                               reported(comments, last['at'], '开发助手'), '开发助手')
    if last['phase'] != 'retry':
        log = ''
        if current and re.fullmatch(r'cnb-[a-z0-9-]+', current['sn'] or ''):
            log = f'https://cnb.cool/{POLICY["cnb"]}/-/build/logs/{current["sn"]}'
        return dispatch_action(parsed, 'retry', last['rung'], tree, log, '', '', '开发助手')
    return dispatch_action(parsed, 'diagnose', 60, tree, '', '', reported(comments, last['at'], '开发助手'), '审查助手')


def _stamp(value):
    import datetime
    return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))


def branch_name(number):
    return f'automation/req-{number}'


def branch_sha(number):
    fetched = git('fetch', '--no-tags', f'https://cnb.cool/{POLICY["cnb"]}.git',
                  f'refs/heads/{branch_name(number)}', check=False)
    if fetched.returncode != 0:
        return ''
    return git('rev-parse', 'FETCH_HEAD')


def contained(sha):
    if not re.fullmatch(r'[a-f0-9]{40}', sha or ''):
        return False
    main = api(f'{GH}/git/ref/heads/main')['object']['sha']
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', main, sha)
    return git('merge-base', '--is-ancestor', sha, main, check=False).returncode == 0


def pull_for(number, pulls):
    name = branch_name(number)
    matching = [item for item in pulls if item['head']['ref'].removeprefix('refs/heads/') == name
                and item['head']['repo']['path'] == POLICY['cnb'] and item.get('state') == 'open']
    return max(matching, key=lambda item: int(item['number']), default=None)


def check_state(number):
    if not number:
        return False, False
    checks = api(f'{CNB}/pulls/{number}/commit-statuses')
    statuses = checks.get('statuses') or []
    failed = any(item['state'] in {'error', 'failure'} for item in statuses)
    green = checks.get('state') == 'success' and bool(statuses) and all(
        item['state'] == 'success' for item in statuses)
    return green, failed


def review_block(pull):
    if not pull:
        return False, ''
    request = scope('cnb', pull)
    if state(request) != 'failure':
        return False, ''
    issue = find_request(request)
    if not issue:
        return True, '结对审核未通过。按阻断项修改后推同一分支。'
    comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
    text = ''
    for item in comments:
        if 'FLCLASH_REVIEW' in item.get('body', '') and '"verdict":"block"' in item.get('body', '').replace(' ', ''):
            text = item.get('body', '')
    return True, (text or '结对审核未通过。按阻断项修改后推同一分支。')[:1500]


def act(issue, action, sha):
    number = str(issue['number'])
    if action['kind'] == 'wait':
        return
    if action['kind'] == 'close':
        close_done(issue, number)
        return
    if action['kind'] == 'forward':
        forward(issue, number, sha)
        return
    payload = {'issue': number, 'scope': parse(issue.get('body', ''))['scope'] if action['phase'] != 'invalid' else 'form',
               'phase': action['phase'], 'rung': action['rung'], 'tree': action.get('tree') or sha or ''}
    if action['kind'] == 'note':
        comment(number, envelope(payload) + '\n\n' + action['body'])
        return
    if action['kind'] == 'stop':
        comment(number, envelope(payload) + '\n\n' + action['body'])
        return
    role = action['role']
    body = (envelope(payload) + '\n\n'
            f'@{POLICY["cnb"]}({role}) 分支 `{branch_name(number)}`。\n' + action['instruction'])
    comment(number, body, action['work_mode'])


def close_done(issue, number):
    pulls = list(pages(f'{CNB}/pulls?state=open'))
    pull = pull_for(number, pulls)
    if pull and pull['state'] == 'open':
        api(f'{CNB}/pulls/{pull["number"]}', 'PATCH', {'state': 'closed'})
    if issue.get('state') == 'open':
        api(f'{CNB}/issues/{number}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})


def forward(issue, number, sha):
    branch = branch_name(number)
    owner_name = POLICY['github'].split('/')[0]
    if api(f'{GH}/pulls?state=open&head={owner_name}:{branch}'):
        return
    closed = api(f'{GH}/pulls?state=closed&head={owner_name}:{branch}')
    if closed:
        previous = list(pages(f'{CNB}/issues/{number}/comments'))
        if not any('保持暂停' in (item.get('body') or '') for item in previous):
            comment(number, f'GitHub PR `{branch}` 已关闭，保持暂停，不重复创建。')
        return
    base = api(f'{GH}/git/ref/heads/main')['object']['sha']
    existing = api(f'{GH}/git/ref/heads/{branch}', missing=True)
    if existing and existing['object']['sha'] != sha:
        print(f'{branch} points at a different commit; not overwriting it')
        return
    if not existing:
        push_github(sha, branch)
    pull = pull_for(number, list(pages(f'{CNB}/pulls?state=open')))
    if not pull:
        return
    payload = {'base': base, 'head': sha, 'tree': git('rev-parse', sha + '^{tree}'),
               'cnb_number': str(pull['number']), 'branch': branch}
    created = api(f'{GH}/pulls', 'POST', {
        'base': 'main', 'head': branch,
        'title': issue.get('title', f'[需求] {number}'),
        'body': '承接 CNB 需求分支。GitHub 是唯一合并入口。检查成功后由控制器合并。\n\n'
                + '<!-- flclash-security-mirror ' + json.dumps(sign(payload)) + ' -->'})
    comment(number, '需求已送至 GitHub：' + created['html_url'])
    review_reconcile()
    from security_finish import dispatch_workflow
    dispatch_workflow('reviews.yaml', 'main')
    ensure_branch_scan(sha, branch)


def reconcile():
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    pulls = list(pages(f'{CNB}/pulls?state=all'))
    for summary in pages(f'{CNB}/issues?state=open'):
        issue = api(f'{CNB}/issues/{summary["number"]}')
        if issue.get('state') != 'open' or not str(issue.get('title', '')).startswith('[需求]') or not owner(issue):
            continue
        number = str(issue['number'])
        comments = list(pages(f'{CNB}/issues/{number}/comments'))
        pull = pull_for(number, pulls)
        if pull:
            pull = api(f'{CNB}/pulls/{pull["number"]}')
            comments += list(pages(f'{CNB}/pulls/{pull["number"]}/comments'))
        sha = branch_sha(number)
        tree = git('rev-parse', sha + '^{tree}') if sha else ''
        rows = attempts([issue] + comments)
        for row in rows:
            if re.fullmatch(r'cnb-[a-z0-9-]+', row['sn'] or ''):
                status = api(f'{CNB}/build/status/{row["sn"]}', missing=True) or {}
                row['detail'] = (row['detail'] + '\n' + json.dumps(status, ensure_ascii=False))[:500]
        green, failed = check_state(pull['number'] if pull else '')
        blocked, text = review_block(pull) if failed or (pull and not green) else (False, '')
        if failed and not text:
            text = 'CI 未通过。先读失败日志，再推同一分支。'
            blocked = False
        action = decide(issue, comments, rows, tree, contained(sha), green, blocked, text, now)
        if action['kind'] == 'dispatch' and failed:
            action['instruction'] += '\n' + text
        act(issue, action, sha)


if __name__ == '__main__':
    reconcile()
