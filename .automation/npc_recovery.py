import hashlib
import json
import re

from control import CNB, POLICY, api, comment, pages, parse_request, sign, verify
from reviews import ROLES, identity, request_from
from security_watch import record
from security_groups import GROUPS, repair_branch


def owner(item):
    author = item.get('author') or {}
    return author.get('username') == POLICY['approver'] and author.get('is_npc') is False


def task(issue):
    if str(issue.get('title', '')).startswith('[需求]'):
        return None
    request = request_from(issue)
    if request:
        sample = json.dumps({'request': identity(request), 'verdict': 'pass', 'blockers': 0})
        return identity(request), ROLES, False, (
            f'只审核固定 base `{request["base"]}`、head `{request["head"]}`。'
            '默认检出 main 不一定包含 PR 文件，请 git fetch 后用 git show 指定 head 读取；不要调查文件为何不在 main。'
            '只有完成审核且无阻断才能使用下面的 pass/0；否则改为 block 并列证据。'
            f'最终必须单独一行输出，不放代码块：\nFLCLASH_REVIEW {sample}\n')
    security = record(issue)
    if security and security.get('group') in GROUPS:
        return None
    if security:
        return security['key'], ('开发助手',), True, (
            f'继续评估 `{security["package"]}`（`{security["file"]}`），'
            f'复用已有 `{repair_branch(security)}` 分支，先检查远端是否已有提交或 PR，不覆盖人工修改。'
            '统一处理组内依赖，不另开单包任务。允许有证据的部分修复，暂无修复的条目保留；整组需要变更工具链或跨大版本时停止并报告。'
            '保留已完成改动；验证不完整可提交草稿 PR 并明确未验证项，不得声称修复完成。')
    if owner(issue):
        try:
            request = parse_request(issue.get('body', ''))
        except (ValueError, KeyError, TypeError):
            return None
        if request:
            return request['sha'], ('上游更新助手', 'GLM复核助手'), False, (
                f'只分析已固定上游 {request["tag"]} / {request["sha"]}；不批准、修改代码或发版。')
        match = re.fullmatch(r'\[构建待处理\] GitHub #(\d+)', issue['title'])
        if match:
            return match[1], ('审查助手',), False, (
                f'只读取 GitHub 构建 {match[1]} 的失败步骤和 Failing tests 汇总，'
                '不要把预期异常测试的日志当成真实失败。只给出文件、根因和建议，不重跑构建。')
    return None


def latest_attempts(issue, comments):
    attempts = {}
    for container in [issue] + sorted(comments, key=lambda c: (c.get('created_at', ''), int(c['id']))):
        for entry in (container.get('statuses') or {}).get('npc', []):
            context = entry.get('context') or {}
            if context.get('npc.slug') != POLICY['cnb']:
                continue
            states = entry.get('statuses') or []
            if states:
                attempts[context.get('npc.name')] = (states[-1].get('state'), context,
                                                     container.get('created_at', ''))
    return attempts


def recovery_marker(key, phase):
    return '<!-- flclash-npc-recovery ' + json.dumps(sign({'key': key, 'phase': phase})) + ' -->'


def has_marker(comments, key, phase):
    for item in comments:
        if not owner(item):
            continue
        match = re.search(r'<!-- flclash-npc-recovery (\{[^\r\n]+\}) -->', item.get('body', ''))
        if match:
            try:
                if verify(json.loads(match[1])) == {'key': key, 'phase': phase}:
                    return True
            except (ValueError, KeyError, TypeError):
                continue
    return False


def recover():
    actions = 0
    for summary in pages(f'{CNB}/issues?state=open'):
        issue = api(f'{CNB}/issues/{summary["number"]}')
        if issue.get('state') != 'open':
            continue
        spec = task(issue)
        if not spec:
            continue
        scope, roles, work_mode, instruction = spec
        comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
        if work_mode:
            for item in sorted(comments, key=lambda c: (c.get('created_at', ''), int(c['id']))):
                revision = re.search(r'<!-- security-work-requested ' + re.escape(spec[0])
                                     + r':([a-f0-9]{16}) -->', item.get('body', ''))
                if owner(item) and revision:
                    scope = spec[0] + ':' + revision[1]
        for role, (state, context, started) in latest_attempts(issue, comments).items():
            if role not in roles or state not in ('error', 'failure'):
                continue
            if any(c.get('author', {}).get('username') == f'{POLICY["cnb"]}({role})'
                   and c.get('author', {}).get('is_npc') is True
                   and c.get('created_at', '') >= started for c in comments):
                continue
            key = hashlib.sha256(f'{issue["number"]}:{scope}:{role}'.encode()).hexdigest()
            if has_marker(comments, key, 'retry'):
                retries = [c for c in comments if has_marker([c], key, 'retry')]
                if started < max(c.get('created_at', '') for c in retries):
                    continue
                if not has_marker(comments, key, 'stopped'):
                    comment(issue['number'], recovery_marker(key, 'stopped')
                            + f'\n\n{role} 的一次自动恢复仍未完成，已停止继续重试。请人工处理，未作通过判定。')
                continue
            if actions >= 2:
                return
            sn = context.get('sn', '')
            if not re.fullmatch(r'cnb-[a-z0-9-]+', sn):
                continue
            status = api(f'{CNB}/build/status/{sn}')
            if status['status'] not in ('error', 'failure'):
                continue
            comment(issue['number'], recovery_marker(key, 'retry')
                + f'\n\n上次 {role} 任务失败且没有留下报告，执行唯一一次自动恢复。'
                f'日志：https://cnb.cool/{POLICY["cnb"]}/-/build/logs/{sn}\n\n'
                f'@{POLICY["cnb"]}({role}) {instruction}'
                '最多12次工具调用或5分钟后立即提交阶段报告；不必一次解决全部问题。'
                '合并相关查询，不重复搜索已确认的信息，不sleep、不轮询另一位报告，不自动召唤任何 NPC。'
                '到预算前优先发布结论；未完成必须明确说明，不回复 OK，不合并、不发布、不忽略测试或告警。', work_mode)
            actions += 1


if __name__ == '__main__':
    recover()
