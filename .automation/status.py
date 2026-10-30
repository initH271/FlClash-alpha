"""Keep one owner-facing CNB issue that lists automation work no state machine is moving."""
import json
import re
import time

import pause
from control import CNB, GH, POLICY, ROOT, api, approved, pages, release_identity, version
from npc_recovery import latest_attempts
from wake import HALTED, SETTLED, _age, _signed

TITLE = '[自动化状态] 卡点汇总'
MARKER = '<!-- flclash-automation-status -->'
HOLD_ALERT_SECONDS = 2 * 60 * 60


def span(seconds):
    """Coarse on purpose: the body only changes, and is only patched, when a bucket rolls over."""
    minutes = max(0, int(seconds // 60))
    if minutes < 10:
        return '不到 10 分钟'
    if minutes < 120:
        return f'{minutes // 10 * 10} 分钟'
    hours = minutes // 60
    return f'{hours} 小时' if hours < 48 else f'{hours // 24} 天'


def _link(kind, number):
    return f'[#{number}](https://cnb.cool/{POLICY["cnb"]}/-/{kind}/{number})'


def _opened(age):
    return '时长未知' if age is None else span(age)


def _stage(row):
    if row['state'] != 'open':
        return '**【需求已关闭，孤儿 PR】**'
    if row['hold'] is not None:
        return f'**【HOLD】** {row["phase"]}'
    return f'**【{row["phase"]}】**' if row['phase'] in HALTED else row['phase']


def render(snapshot):
    """Build the status body from collected data alone, so its format is testable offline."""
    lines = ['## 需求 PR']
    lines += [f'- PR {_link("pulls", row["pull"])} {row["title"]}：开了 {_opened(row["age"])}，'
              f'需求 {_link("issues", row["requirement"])} {_stage(row)}' for row in snapshot['pulls']] or ['- 无']
    held = [row for row in snapshot['pulls'] if (row['hold'] or 0) > HOLD_ALERT_SECONDS]
    if held:
        lines += ['', '### HOLD 超过 2 小时']
        lines += [f'- 需求 {_link("issues", row["requirement"])}（PR {_link("pulls", row["pull"])}）：'
                  f'HOLD 已 {span(row["hold"])}' for row in held]
    lines += ['', '## 待 owner OK 的升级']
    lines += [f'- {_link("issues", row["issue"])} {row["tag"]}：等了 {int(row["waited"] // 86400)} 天'
              for row in snapshot['upgrades']] or ['- 无']
    lead = snapshot['release']
    lines += ['', '## 发版']
    if lead.get('ahead') is None:
        lines.append(f'- 最新 release {lead["tag"]}：{lead["note"]}')
    elif lead['ahead']:
        lines.append(f'- **GitHub main 领先最新 release {lead["tag"]} {lead["ahead"]} 个提交**')
    else:
        lines.append(f'- GitHub main 与最新 release {lead["tag"]} 一致')
    lines += ['', '## 正在运行的 NPC 构建']
    lines += [f'- 需求 {_link("issues", row["issue"])} {row["role"]} 构建 `{row["sn"]}`：已运行 {span(row["elapsed"])}'
              for row in snapshot['builds']] or ['- 无']
    return '\n'.join(lines) + '\n'


def release_lead():
    tag = release_identity(json.loads((ROOT / '.github/release.json').read_text()))['tag']
    try:
        if api(f'{GH}/releases/tags/{tag}', missing=True) is None:
            return {'tag': tag, 'ahead': None, 'note': 'release.json 里的版本还没有发布'}
        return {'tag': tag, 'ahead': int(api(f'{GH}/compare/{tag}...main')['ahead_by'])}
    except (RuntimeError, KeyError, TypeError, ValueError):
        return {'tag': tag, 'ahead': None, 'note': 'GitHub 读取失败'}


def _owned(issue):
    author = issue.get('author') or {}
    return author.get('username') == POLICY['approver'] and author.get('is_npc') is False


def collect(issues, now):
    snapshot = {'pulls': [], 'upgrades': [], 'builds': [], 'release': release_lead()}
    pulls = {}
    for pull in pages(f'{CNB}/pulls?state=open'):
        match = re.fullmatch(r'automation/req-(\d+)', pull['head']['ref'].removeprefix('refs/heads/'))
        if match:
            pulls[match[1]] = pull
    numbers = [str(item['number']) for item in issues
               if str(item.get('title', '')).startswith('[需求]') and _owned(item)]
    for number in dict.fromkeys(numbers + list(pulls)):
        issue = api(f'{CNB}/issues/{number}', missing=True) or {}
        comments = list(pages(f'{CNB}/issues/{number}/comments')) if issue else []
        for role, (state, context, started) in latest_attempts(issue, comments).items():
            if state not in SETTLED and started:
                snapshot['builds'].append({'issue': number, 'role': role, 'sn': context.get('sn', ''),
                                           'elapsed': _age(started, now)})
        if number not in pulls:
            continue
        signed = _signed(comments)
        hold = pause.held(comments)
        snapshot['pulls'].append({
            'pull': str(pulls[number]['number']), 'requirement': number,
            'title': ' '.join(str(pulls[number].get('title', '')).split()).replace('@', '＠')[:60],
            'age': _age(pulls[number]['created_at'], now) if pulls[number].get('created_at') else None, 'state': issue.get('state', 'missing'),
            'phase': signed[-1][1].get('phase', '未知') if signed else '未派发',
            'hold': _age(hold, now) if hold else None})
    for item in issues:
        tag = str(item.get('title', '')).removeprefix('[上游升级] FlClash ')
        if tag == item.get('title') or not version(tag) or version(tag) <= version(POLICY['upstream_tag']):
            continue
        if not any(approved(c, tag) for c in pages(f'{CNB}/issues/{item["number"]}/comments')):
            snapshot['upgrades'].append({'issue': str(item['number']), 'tag': tag,
                                         'waited': _age(item['created_at'], now)})
    return snapshot


def publish(body, issues):
    """Patch the one marked status issue in place, create it when missing, and skip an unchanged body."""
    text = MARKER + '\n\n' + body
    for item in issues:
        if item.get('title') != TITLE:
            continue
        detail = api(f'{CNB}/issues/{item["number"]}', missing=True) or {}
        current = str(detail.get('body') or '')
        if MARKER not in current:
            continue
        if current.replace('\r\n', '\n').strip() != text.strip():
            api(f'{CNB}/issues/{item["number"]}', 'PATCH', {'body': text})
            print(f'Updated status issue #{item["number"]}')
        return
    created = api(f'{CNB}/issues', 'POST', {'title': TITLE, 'body': text, 'work_mode': False,
                                           'assignees': [POLICY['approver']]})
    print(f'Created status issue #{created["number"]}')


def refresh(now=None):
    now = time.time() if now is None else now
    issues = list(pages(f'{CNB}/issues?state=open'))
    publish(render(collect(issues, now)), issues)
