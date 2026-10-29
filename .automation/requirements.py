import hashlib
import json
import re
import time

import pause
from control import CNB, GH, POLICY, api, check_name, comment, gating_statuses, git, pages, sign, verify
from reviews import find_request, reconcile as review_reconcile, scope, state
from security_finish import ensure_branch_scan, merge_ready, push_github

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
REVIEW_GATE = 'Paired review gate'


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
        # A dispatch the controller did not sign is somebody else's run; it must not move the ladder.
        signed = bool(markers([item]))
        for entry in (item.get('statuses') or {}).get('npc', []):
            context = entry.get('context') or {}
            states = entry.get('statuses') or []
            if context.get('npc.slug') != POLICY['cnb'] or not states:
                continue
            last = states[-1]
            found.append({'at': item.get('created_at', ''), 'state': last.get('state', ''),
                          'detail': last.get('description', ''), 'sn': context.get('sn', ''),
                          'role': context.get('npc.name', ''), 'signed': signed})
    return found


def quota(text):
    return any(word in (text or '') for word in QUOTA)


def next_rung(current):
    if current not in RUNGS or current == RUNGS[-1]:
        return RUNGS[-1]
    return RUNGS[RUNGS.index(current) + 1]


def running(rows):
    return any(row['state'] not in TERMINAL and row['role'] in ROLES for row in rows)


OVERRUN = '<!-- flclash-requirement-overrun {} -->'
OVERRUN_MINUTES = 75
HOLD_MARKER = '<!-- flclash-requirement-hold {} -->'


def overrun(rows, comments, now):
    for row in rows:
        if row['role'] != '开发助手' or row['state'] in TERMINAL:
            continue
        minutes = int((now - _stamp(row['at'])).total_seconds() // 60)
        if minutes <= OVERRUN_MINUTES or OVERRUN.format(row['sn']) in ' '.join(
                item.get('body') or '' for item in comments):
            continue
        return {'kind': 'overrun', 'sn': row['sn'], 'minutes': minutes}
    return None


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


def instruction(parsed, rung, phase, tree, log, note, previous, sha=''):
    reserve = max(1, rung * 3 // 4)
    number = parsed.get('number', '')
    head = f'`{sha or tree}`' if sha or tree else '不存在（首次派发）'
    lines = [
        f'本轮只用 {rung} 轮。约第 {reserve} 轮起停止扩大调查。',
        '本条末尾的「不做什么」优先于你的角色设定和一般习惯。',
        f'派发时远端分支头：{head}。开工前 git fetch；分支上已有提交时，先逐条核对验收标准，全部满足就不改代码，直接开 PR。已核实的事实不要重头搜索。',
        '把已改文件提交到指定分支，允许提交尚未完成的进度。每个提交信息末尾单独一段写 `FlClash-Actor: npc/开发助手`。',
        '本地检查只跑与改动相关的；flutter test 全量最多跑一次，失败后只重跑失败的文件。跑 flutter test 时在命令前加 `GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=false GIT_CONFIG_KEY_1=tag.gpgsign GIT_CONFIG_VALUE_1=false`，不要改全局 git 配置。',
        '环境里已有 Flutter 3.47.6、Go 和 Rust；没有 Android SDK 和 Gradle，不构建 APK，不要现装这些工具。改到 Gradle、Android 构建或 CI 脚本时，在阶段评论的「未实跑」里写明由哪个 CI 阶段覆盖；不能用桩或 mock 代替真实工具后写成已验证。',
        '提交前对改动文件跑 `bash tool/hooks/comment_density.sh <文件…>`，并用 `bash tool/hooks/commit_msg.sh <提交信息文件>` 检查提交信息；不通过就改到通过。',
        '推送前再 git fetch：远端分支头必须仍是上面写的提交或你本轮推的提交，否则不推送，在阶段评论列出远端多出的提交（SHA、作者、标题）后结束。',
        '推送后开 CNB PR（已有就不重开），head 是指定分支，base 是 main。',
        f'然后在需求 Issue #{number} 发阶段评论并结束本轮：写提交 SHA、已核实的事实、已改文件、未完成项、未实跑项。「未实跑」不等于未完成。不要 sleep、等待或轮询 CI，CI 和审核结果由控制器下一轮带给你。',
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


def dispatch_action(parsed, phase, rung, tree, log, note, previous, role, sha=''):
    return {'kind': 'dispatch', 'phase': phase, 'rung': rung, 'tree': tree or '',
            'role': role, 'work_mode': role == '开发助手',
            'instruction': instruction(parsed, rung, phase, tree, log, note, previous, sha)}


def decide(issue, comments, rows, tree, contained, checks_green, review_failed, review_text, now,
           has_pull=False, sha='', behind=False, review_only=False, hold=''):
    parsed = parse(issue.get('body', ''))
    parsed['number'] = str(issue['number'])
    known = [item for item in markers(comments) if item.get('issue') == str(issue['number'])]
    form = [item for item in known if item.get('phase') == 'invalid']
    if parsed['missing']:
        if form:
            return {'kind': 'wait'}
        return {'kind': 'note', 'phase': 'invalid', 'rung': 0, 'tree': '',
                'body': '需求表单不完整，未派开发助手。缺：' + '、'.join(parsed['missing'])}
    if contained:
        return {'kind': 'close'}
    if hold:
        if HOLD_MARKER.format(hold) in ' '.join(item.get('body') or '' for item in comments):
            return {'kind': 'wait'}
        return {'kind': 'hold', 'ref': hold, 'sn': next(
            (row['sn'] for row in rows if row['state'] not in TERMINAL and row['role'] in ROLES), '')}
    scoped = [item for item in known if item.get('scope') == parsed['scope'] and item.get('phase') != 'invalid']
    # Quota and stuck stop spending developer rounds; they never hold back work that already passed.
    if checks_green:
        return {'kind': 'sync-main'} if behind else {'kind': 'forward'}
    stuck = any(item.get('phase') == 'stuck' for item in scoped)
    if stuck and review_only and behind:
        # The developer found nothing to change for a review-only block; a synced head gets a fresh review.
        return {'kind': 'sync-main'}
    if stuck or any(item.get('phase') == 'quota' for item in scoped):
        return {'kind': 'wait'}
    if running(rows):
        return overrun(rows, comments, now) or {'kind': 'wait'}
    rows = [row for row in rows if row.get('signed', True)]
    last = scoped[-1] if scoped else None
    if last and quota(last.get('detail', '')):
        return {'kind': 'wait'}
    later = after(rows, last['at'] if last else '', '开发助手') if last else []
    review_rows = after(rows, last['at'], '审查助手') if last else []
    if later and quota(later[-1]['detail']):
        return {'kind': 'stop', 'phase': 'quota', 'rung': last['rung'], 'tree': tree or '',
                'body': '账户额度用尽，不再加轮次。' + later[-1]['detail'][:300]}
    if not last:
        return dispatch_action(parsed, 'dev', RUNGS[0], tree, '', '', '', '开发助手', sha)
    if not later and not review_rows:
        age = now - _stamp(last['at'])
        if age.total_seconds() > 1800:
            return dispatch_action(parsed, last['phase'], last['rung'], tree, '', '上次派发没有回执，按原档重派。', '',
                               '审查助手' if last['phase'] == 'diagnose' else '开发助手', sha)
        return {'kind': 'wait'}
    if last['phase'] == 'diagnose':
        text = reported(comments, last['at'], '审查助手')
        if not review_rows or review_rows[-1]['state'] not in TERMINAL:
            return {'kind': 'wait'}
        if not text:
            return {'kind': 'stop', 'phase': 'stuck', 'rung': last['rung'], 'tree': tree or '',
                    'body': f'审查没有留下结论，tree `{tree or "无"}` 未变，停止加轮次。'}
        return dispatch_action(parsed, 'targeted', last['rung'], tree, '', text, '', '开发助手', sha)
    if last['phase'] == 'targeted' and (not tree or tree == last.get('tree')):
        if not later or later[-1]['state'] not in TERMINAL:
            return {'kind': 'wait'}
        return {'kind': 'stop', 'phase': 'stuck', 'rung': last['rung'], 'tree': tree or '',
                'body': f'换了做法之后 tree `{tree or "无"}` 仍未变化，停止加轮次。'}
    current = later[-1] if later else None
    if current and current['state'] not in TERMINAL:
        return {'kind': 'wait'}
    if current and current['state'] == 'success' and tree and not review_failed:
        if not has_pull:
            return {'kind': 'open-pr', 'tree': tree}
        return {'kind': 'wait'}
    progressed = bool(tree) and tree != (last.get('tree') or '')
    if review_failed and not (last['phase'] == 'targeted' and last.get('tree') == tree):
        return dispatch_action(parsed, 'targeted', next_rung(last['rung']), tree, '', review_text,
                               reported(comments, last['at'], '开发助手'), '开发助手', sha)
    if current and not re.fullmatch(r'cnb-[a-z0-9-]+', current['sn'] or ''):
        return dispatch_action(parsed, 'retry', last['rung'], tree, '', '上次构建号异常，按原档续跑。', '', '开发助手', sha)
    if progressed:
        note = '先读失败日志，改完推同一分支。' if review_failed else ''
        return dispatch_action(parsed, 'dev', next_rung(last['rung']), tree, '', note,
                               reported(comments, last['at'], '开发助手'), '开发助手', sha)
    if last['phase'] != 'retry':
        log = ''
        if current and re.fullmatch(r'cnb-[a-z0-9-]+', current['sn'] or ''):
            log = f'https://cnb.cool/{POLICY["cnb"]}/-/build/logs/{current["sn"]}'
        return dispatch_action(parsed, 'retry', last['rung'], tree, log, '', '', '开发助手', sha)
    return dispatch_action(parsed, 'diagnose', 60, tree, '', '', reported(comments, last['at'], '开发助手'), '审查助手', sha)


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


def check_state(number, pull=None):
    if not number:
        return False, False
    statuses = gating_statuses(api(f'{CNB}/pulls/{number}/commit-statuses'))
    if pull and any(check_name(item) == REVIEW_GATE and item['state'] != 'success' for item in statuses):
        # The gate only polls for 32 minutes; a review that finishes later must still count.
        if state(scope('cnb', pull)) == 'success':
            statuses = [item for item in statuses if check_name(item) != REVIEW_GATE]
    failed = any(item['state'] in {'error', 'failure'} for item in statuses)
    green = bool(statuses) and all(item['state'] == 'success' for item in statuses)
    return green, failed


def ci_passed(number):
    statuses = [item for item in gating_statuses(api(f'{CNB}/pulls/{number}/commit-statuses'))
                if check_name(item) != REVIEW_GATE]
    return bool(statuses) and all(item['state'] == 'success' for item in statuses)


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
    if action['kind'] == 'open-pr':
        open_cnb_pr(issue, number, sha)
        return
    if action['kind'] == 'sync-main':
        sync_main(number, sha)
        return
    if action['kind'] == 'hold':
        hold_notice(number, action)
        return
    if action['kind'] == 'overrun':
        comment(number, OVERRUN.format(action['sn']) + '\n\n'
                + f'开发助手构建 `{action["sn"]}` 已运行约 {action["minutes"]} 分钟，还没结束。'
                '控制器不重复派发；开发阶段的 60 分钟超时没有生效，请 owner 查看构建。')
        return
    payload = {'issue': number, 'scope': parse(issue.get('body', ''))['scope'] if action['phase'] != 'invalid' else 'form',
               'phase': action['phase'], 'rung': action['rung'], 'tree': action.get('tree') or sha or '',
               'head': sha}
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


HOLD_NOTICE = ('owner 已占用分支 `{branch}`：控制器暂停派发、开 PR、同步 main 和转发。'
               '推完提交后发 RELEASE 恢复；新提交照常要过 CNB 检查和结对审核。'
               '已经转发到 GitHub 的 PR 不在本轮暂停范围内，要防止它被合并，请先把 GitHub PR 转为草稿。')
HOLD_RUNNING = '开发助手构建 `{sn}` 仍在运行，HOLD 拦不住它的推送，等它结束或在 CNB 上手动停止后再推。'


def hold_notice(number, action):
    number = str(number)
    body = HOLD_MARKER.format(action['ref']) + '\n\n' + HOLD_NOTICE.format(branch=branch_name(number))
    if action.get('sn'):
        body += '\n\n' + HOLD_RUNNING.format(sn=action['sn'])
    comment(number, body)


def close_done(issue, number):
    pulls = list(pages(f'{CNB}/pulls?state=open'))
    pull = pull_for(number, pulls)
    if pull and pull['state'] == 'open':
        api(f'{CNB}/pulls/{pull["number"]}', 'PATCH', {'state': 'closed'})
    if issue.get('state') == 'open':
        api(f'{CNB}/issues/{number}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})


def open_cnb_pr(issue, number, sha):
    if pull_for(number, list(pages(f'{CNB}/pulls?state=open'))):
        return
    api(f'{CNB}/pulls', 'POST', {
        'base': 'main', 'head': branch_name(number),
        'title': issue.get('title', f'[需求] {number}'),
        'body': f'需求 #{number}，提交 `{sha}`。检查由流水线跑，控制器不在这里合并。'})


def mirror_body(payload, origins=()):
    lines = ('**提交归属**\n\n' + '\n'.join(origins) + '\n\n') if origins else ''
    return ('承接 CNB 需求分支。GitHub 是唯一合并入口。检查成功后由控制器合并。\n\n'
            + lines
            + '<!-- flclash-security-mirror ' + json.dumps(sign(payload)) + ' -->')


def commit_rows(since, sha, limit, skip_actor=False):
    """Return (sha, author, subject) per commit in since..sha, or [] when git cannot list them.

    The start is fetched first: a requirement commit is not always local, and a bare `git log` failure
    would otherwise look like an empty branch.
    """
    if not (re.fullmatch(r'[a-f0-9]{40}', since or '') and re.fullmatch(r'[a-f0-9]{40}', sha or '')):
        return []
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', since, check=False)
    log = git('log', '--first-parent', f'--max-count={limit}',
              '--format=%H%x1f%an%x1f%s%x1f%(trailers:key=FlClash-Actor,valueonly,separator=%x2c)%x1e',
              f'{since}..{sha}', check=False)
    if log.returncode:
        print(f'cannot list commits {since[:12]}..{sha[:12]}; origin report skipped')
        return []
    rows = []
    for record in filter(None, (item.strip() for item in log.stdout.split('\x1e'))):
        fields = record.split('\x1f')
        if len(fields) < 3:
            continue
        actor = fields[3].strip() if len(fields) > 3 else ''
        if skip_actor and actor:
            continue
        rows.append((fields[0], fields[1], fields[2], actor))
    return rows


def escaped(text):
    """Keep a branch payload from closing the mirror marker it is quoted inside."""
    return text.replace('<', '&lt;')


def origin_rows(base, sha, limit=20):
    rows = []
    for commit, author, subject, actor in commit_rows(base, sha, limit):
        origin = actor or f'人工（无 FlClash-Actor，作者 {author}）'
        rows.append('- `{}` 归属：{}：{}'.format(commit[:8], escaped(origin), escaped(subject[:80])))
    return rows


def foreign_commits(since, sha, limit=10):
    """Return (sha, author, subject) for commits on the branch that carry no FlClash-Actor trailer."""
    if not (re.fullmatch(r'[a-f0-9]{40}', since or '') and re.fullmatch(r'[a-f0-9]{40}', sha or '')):
        return []
    if since == sha:
        return []
    return [row[:3] for row in commit_rows(since, sha, limit, skip_actor=True)]


def forward(issue, number, sha):
    branch = branch_name(number)
    owner_name = POLICY['github'].split('/')[0]
    opened = api(f'{GH}/pulls?state=open&head={owner_name}:{branch}')
    if opened:
        advance(issue, number, sha, opened[0])
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
        'body': mirror_body(payload, origin_rows(base, sha))})
    comment(number, '需求已送至 GitHub：' + created['html_url'])
    settle(issue, number, sha, created['number'])


def advance(issue, number, sha, pull):
    # The CNB branch moved on (usually a main sync); fast-forward the open GitHub PR to it.
    old = pull['head']['sha']
    if old == sha:
        return
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', old)
    if git('merge-base', '--is-ancestor', old, sha, check=False).returncode != 0:
        print(f'{branch_name(number)} on GitHub is not an ancestor of {sha}; not overwriting it')
        return
    source = pull_for(number, list(pages(f'{CNB}/pulls?state=open')))
    if not source:
        return
    push_github(sha, branch_name(number))
    base = api(f'{GH}/git/ref/heads/main')['object']['sha']
    payload = {'base': base, 'head': sha,
               'tree': git('rev-parse', sha + '^{tree}'), 'cnb_number': str(source['number']),
               'branch': branch_name(number)}
    api(f'{GH}/pulls/{pull["number"]}', 'PATCH', {'body': mirror_body(payload, origin_rows(base, sha))})
    comment(number, f'GitHub PR 已跟进到 `{sha[:12]}`：' + pull['html_url'])
    settle(issue, number, sha, pull['number'])


def settle(issue, number, sha, pull_number):
    review_reconcile()
    from security_finish import dispatch_workflow
    dispatch_workflow('reviews.yaml', 'main')
    ensure_branch_scan(sha, branch_name(number))
    if merge_when_settled(pull_number):
        close_done(issue, number)


def main_drift(sha):
    """Return (behind, conflict) for the requirement commit against GitHub main."""
    main = api(f'{GH}/git/ref/heads/main')['object']['sha']
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', main)
    if git('merge-base', '--is-ancestor', main, sha, check=False).returncode == 0:
        return False, False
    merged = git('merge-tree', '--write-tree', sha, main, check=False)
    return True, merged.returncode != 0


def sync_main(number, sha):
    branch = branch_name(number)
    main = api(f'{GH}/git/ref/heads/main')['object']['sha']
    git('fetch', '--no-tags', f'https://github.com/{POLICY["github"]}.git', main)
    merged = git('merge-tree', '--write-tree', sha, main, check=False)
    if merged.returncode != 0:
        return
    commit = git('commit-tree', merged.stdout.splitlines()[0], '-p', sha, '-p', main,
                 '-m', f'Merge main into {branch}', '-m', 'FlClash-Actor: controller')
    from control import sync_branch
    sync_branch(branch, commit)
    comment(number, f'分支落后 main，已把 main（`{main[:12]}`）合入 `{branch}`，新提交 `{commit[:12]}`。'
            '检查和结对审核会在新提交上重跑。')


def merge_when_settled(number, attempts=12, pause=10):
    # Nothing else wakes the controller after this run, so merge here once GitHub settles.
    for _ in range(attempts):
        if api(f'{GH}/pulls/{number}').get('mergeable_state') in {'clean', 'unstable'}:
            break
        time.sleep(pause)
    merge_ready()
    return bool(api(f'{GH}/pulls/{number}').get('merged'))


def reconcile():
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    pulls = list(pages(f'{CNB}/pulls?state=all'))
    for summary in pages(f'{CNB}/issues?state=open'):
        issue = api(f'{CNB}/issues/{summary["number"]}')
        if issue.get('state') != 'open' or not str(issue.get('title', '')).startswith('[需求]') or not owner(issue):
            continue
        number = str(issue['number'])
        issue_comments = list(pages(f'{CNB}/issues/{number}/comments'))
        comments = list(issue_comments)
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
        green, failed = check_state(pull['number'] if pull else '', pull)
        blocked, text = review_block(pull) if failed or (pull and not green) else (False, '')
        if failed and not text:
            text = 'CI 未通过。先读失败日志，再推同一分支。'
            blocked = False
        behind = review_only = False
        if green:
            behind, conflict = main_drift(sha)
            if conflict:
                green, blocked = False, True
                text = '分支落后 main 且合并有冲突。先把最新 main 合进指定分支、解决冲突并跑相关测试，再推同一分支。'
        elif blocked and pull and sha and ci_passed(pull['number']):
            review_only = True
            behind, conflict = main_drift(sha)
            behind = behind and not conflict
        hold = pause.paused('branch', branch_name(number), issue_comments) or {}
        action = decide(issue, comments, rows, tree, contained(sha), green, blocked, text, now,
                        has_pull=bool(pull), sha=sha, behind=behind, review_only=review_only,
                        hold=hold.get('since', ''))
        if action['kind'] == 'dispatch' and failed:
            action['instruction'] += '\n' + text
        if action['kind'] == 'dispatch':
            foreign = foreign_commits(dispatch_start(known_marks(number, issue_comments), sha), sha)
            if foreign:
                action['instruction'] += '\n' + FOREIGN_NOTE + '；'.join(
                    f'{item[0][:8]} {item[1]} {item[2]}' for item in foreign) + '。先读这些提交，不要回退或覆盖。'
        act(issue, action, sha)


FOREIGN_NOTE = '分支上有不是开发助手推的提交：'


def known_marks(number, comments):
    return [item for item in markers(comments)
            if item.get('issue') == str(number) and item.get('phase') in ('dev', 'retry', 'targeted', 'diagnose')]


def dispatch_start(marks, sha):
    """Where the branch was before this round: the last signed dispatch head, else GitHub main."""
    for item in reversed(marks):
        head = item.get('head')
        if re.fullmatch(r'[a-f0-9]{40}', head or ''):
            return head
    main = api(f'{GH}/git/ref/heads/main')['object']['sha']
    return main if re.fullmatch(r'[a-f0-9]{40}', main or '') else ''


if __name__ == '__main__':
    reconcile()
