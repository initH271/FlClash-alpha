import datetime
import hashlib
import json
import re

from control import CNB, POLICY, api, comment, pages, sign, verify
from security_groups import GROUPS, repair_branch
from security_scan import key
from security_watch import record

TERMINAL = {'success', 'error', 'failure', 'cancel', 'cancelled'}


def owner(item):
    author = item.get('author') or {}
    return author.get('username') == POLICY['approver'] and author.get('is_npc') is False


def revision(payload):
    aliases = sorted({key(row) + ':' + alias for row in payload['history']
                      if row['state'] == '待评估（扫描命中）' for alias in row['aliases']})
    return hashlib.sha256(json.dumps(aliases).encode()).hexdigest()[:16] if aliases else None


def attempts(items):
    result = []
    for item in items:
        for entry in (item.get('statuses') or {}).get('npc', []):
            context = entry.get('context') or {}
            states = entry.get('statuses') or []
            if (context.get('npc.slug') == POLICY['cnb'] and context.get('npc.name') == '开发助手'
                    and states):
                result.append((item.get('created_at', ''), states[-1]['state'], context.get('sn', '')))
    return sorted(set(result))


def checkpoints(comments, scope):
    result = []
    for item in comments:
        if not owner(item):
            continue
        match = re.search(r'<!-- flclash-security-run (\{[^\r\n]+\}) -->', item.get('body', ''))
        if not match:
            continue
        try:
            data = verify(json.loads(match[1]))
            if data['scope'] == scope:
                result.append((item['created_at'], data))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(result, key=lambda entry: entry[0])


def decision(payload, issue, comments, pull, pull_comments, now):
    rev = revision(payload)
    scope = payload['key'] + ':' + (rev or 'none')
    history = attempts([issue] + comments + pull_comments)
    runs = checkpoints(comments, scope)
    latest = history[-1] if history else None
    running = [a for a in history if a[1] not in TERMINAL]
    if running:
        started = min(a[0] for a in running)
        age = now - datetime.datetime.fromisoformat(started.replace('Z', '+00:00'))
        return ('stalled' if age.total_seconds() > 1800 else 'running'), scope, latest
    if runs and (not latest or runs[-1][0] > latest[0]):
        age = now - datetime.datetime.fromisoformat(runs[-1][0].replace('Z', '+00:00'))
        return ('dispatch-stalled' if age.total_seconds() > 1800 else 'awaiting-start'), scope, latest
    if pull and pull.get('is_merged'):
        return 'rescan', scope, latest
    if pull and pull['state'] != 'open':
        return 'attention', scope, latest
    if not rev:
        return 'assessment', scope, latest
    if latest and latest[1] in {'error', 'failure'}:
        if runs and any(data['phase'] == 'resume' for _, data in runs):
            return 'attention', scope, latest
        if any(c.get('author', {}).get('is_npc') is True
               and c.get('author', {}).get('username') == f'{POLICY["cnb"]}(开发助手)'
               and c.get('created_at', '') >= latest[0] for c in comments + pull_comments):
            return 'reported', scope, latest
        return 'resume', scope, latest
    if pull:
        return ('rescan' if pull.get('is_merged') else 'pr-open' if pull['state'] == 'open'
                else 'attention'), scope, latest
    legacy = '<!-- security-work-requested ' + scope + ' -->'
    if latest or runs or any(owner(c) and legacy in c.get('body', '') for c in comments):
        return 'reported' if latest and latest[1] == 'success' else 'attention', scope, latest
    return 'start', scope, latest


def snapshot(issue, phase, pull, latest):
    labels = {'start': '排队中', 'resume': '等待接续', 'running': '开发执行中',
              'stalled': '执行超过30分钟，需核实运行状态', 'awaiting-start': '已派发，等待平台确认',
              'dispatch-stalled': '派发超过30分钟仍无回执，需人工核实；保留名额避免重复执行',
              'attention': '需要人工处理，自动接续预算已用完或任务已终止',
              'reported': '已有阶段报告，等待人工评估', 'assessment': '需要评估未索引项',
              'pr-open': '已提交 PR，等待检查和审核', 'rescan': 'PR 已合并，等待主分支复扫'}
    detail = labels[phase]
    if pull:
        detail += f'；[PR #{pull["number"]}](https://cnb.cool/{POLICY["cnb"]}/-/pulls/{pull["number"]})'
    if latest:
        detail += f'；最近执行 `{latest[2]}`：{latest[1]}'
    block = '<!-- security-progress:start -->\n**自动化进度：** ' + detail + '\n<!-- security-progress:end -->'
    body = issue['body']
    if '<!-- security-progress:start -->' in body:
        updated = re.sub(r'<!-- security-progress:start -->.*?<!-- security-progress:end -->',
                         lambda _: block, body, flags=re.S)
    else:
        updated = block + '\n\n' + body
    if updated != body:
        api(f'{CNB}/issues/{issue["number"]}', 'PATCH', {'body': updated})
        if phase in {'attention', 'stalled', 'dispatch-stalled'}:
            comment(issue['number'], '自动化需要处理：' + detail + '。未作通过或修复完成判定。')


def reconcile():
    now = datetime.datetime.now(datetime.timezone.utc)
    pulls = list(pages(f'{CNB}/pulls?state=all'))
    tasks = []
    for summary in pages(f'{CNB}/issues?state=open'):
        issue = api(f'{CNB}/issues/{summary["number"]}')
        payload = record(issue)
        if issue.get('state') != 'open' or not payload or payload.get('group') not in GROUPS:
            continue
        matching = [p for p in pulls if p['head']['ref'].removeprefix('refs/heads/') == repair_branch(payload)
                    and p['head']['repo']['path'] == POLICY['cnb']]
        pull = max(matching, key=lambda p: int(p['number']), default=None)
        comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
        pc = list(pages(f'{CNB}/pulls/{pull["number"]}/comments')) if pull else []
        phase, scope, latest = decision(payload, issue, comments, pull, pc, now)
        tasks.append((issue, payload, pull, phase, scope, latest))
    occupied = sum(phase in {'running', 'stalled', 'awaiting-start', 'dispatch-stalled'}
                   for _, _, _, phase, _, _ in tasks)
    # Start untouched groups before retries so a failed group cannot starve the queue.
    tasks.sort(key=lambda t: (t[3] != 'start', int(t[0]['number'])))
    for issue, payload, pull, phase, scope, latest in tasks:
        if phase in {'start', 'resume'} and occupied < 2:
            if latest:
                if not re.fullmatch(r'cnb-[a-z0-9-]+', latest[2]):
                    phase = 'attention'
                elif api(f'{CNB}/build/status/{latest[2]}')['status'] not in {'error', 'failure'}:
                    phase = 'awaiting-start'
                    occupied += 1
            if phase in {'start', 'resume'}:
                head = pull['head']['sha'] if pull else None
                checkpoint = {'scope': scope, 'phase': phase, 'head': head,
                              'previous_run': latest[2] if latest else None}
                marker = '<!-- flclash-security-run ' + json.dumps(sign(checkpoint)) + ' -->'
                target = f'关联 PR #{pull["number"]}，先读最新 CI 失败和已有提交。' if pull else '已有远端分支时先读取断点。'
                comment(issue['number'], marker + '\n\n'
                    f'@{POLICY["cnb"]}(开发助手) {target}复用 `{repair_branch(payload)}`。'
                    '本轮只交付一个可验证的阶段：先核对现状，再做最小兼容修复，最后提交报告。'
                    '优先保留已有工作；允许草稿 PR 和有证据的部分修复，剩余项留在本任务。'
                    'Go CI 为1.26.4，根模块可通过 MVS 提升间接依赖。不要按单个依赖拆任务。'
                    '最多12次工具调用或5分钟，预留最后2次发布提交/阶段报告。'
                    '报告必须含分支/提交、实际测试、未完成项和下一步；工具缺失应明确记录。'
                    '不等待其他助手、不自行召唤、不忽略失败、不修改权限或流水线、不合并发版。', True)
                occupied += 1
                phase = 'awaiting-start'
        snapshot(issue, phase, pull, latest)


if __name__ == '__main__':
    reconcile()
