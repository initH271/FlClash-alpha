import hashlib
import json
import re

import pause
from control import CNB, POLICY, api, comment, pages, parse_request, sign, verify
from reviews import (BUDGET, EVIDENCE_RULES, ROLES, _checkpoint, _owner_comment, budget_text, endpoint, identity,
                     progress, request_from, role_reports)
from security_watch import record
from security_groups import GROUPS, repair_branch


# A reviewer whose latest summon ended without a report is summoned again, up to this many times per request and role.
RESEND_LIMIT = 2
# An unanswered first summon, or any later one, is given this long before its run is stopped or the summon counted lost.
REVIEW_SECONDS, FOLLOWUP_SECONDS = 40 * 60, 20 * 60
# A run's report goes up before the run ends, so a short wait is enough to see it.
SETTLE_SECONDS = 3 * 60
# Doubles with each resend: two rate-limited runs 90 seconds apart were not spaced out enough to recover (#296).
RATE_LIMIT_SECONDS = 15 * 60
FINISHED = ('success', 'error', 'failure', 'cancel', 'cancelled')
EXCERPT_CHARS = 12000
ANSI = re.compile(r'\x1b\[[0-9;]*m')
AGENT_LINE = re.compile(r'Master\[agent\]\[\d+\] \S+ \S+ ?')


def owner(item):
    author = item.get('author') or {}
    return author.get('username') == POLICY['approver'] and author.get('is_npc') is False


def task(issue):
    if str(issue.get('title', '')).startswith('[需求]'):
        return None
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


def review_instruction(request, budget):
    sample = json.dumps({'request': identity(request), 'verdict': 'pass', 'blockers': 0})
    paths = (request.get('shard') or {}).get('paths')
    return (f'只审核固定 base `{request["base"]}`、head `{request["head"]}`。'
            + (f'本分片只审这些文件：{"、".join(f"`{path}`" for path in paths)}。' if paths else '')
            + '默认检出 main 不一定包含 PR 文件，请 git fetch 后用 git show 指定 head 读取；不要调查文件为何不在 main。'
            '只有完成审核且无阻断才能使用下面的 pass/0；否则改为 block 并列证据。'
            + EVIDENCE_RULES + budget_text(budget)
            + f'最终必须单独一行输出，不放代码块：\nFLCLASH_REVIEW {sample}\n')


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


HUNG_SECONDS = 60 * 60
MAX_PER_PASS = 2


def hung(state, started, now):
    import datetime
    if state in ('success', 'error', 'failure', 'cancel', 'cancelled') or not started:
        return False
    begun = datetime.datetime.fromisoformat(started.replace('Z', '+00:00'))
    return (now - begun).total_seconds() > HUNG_SECONDS


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


def _final_stage(sn, build, context):
    """Read the log stage of the model that ran: {} when the build never got as far as one."""
    pipelines = build.get('pipelinesStatus') or {}
    pipeline = pipelines.get(context.get('pipeline_id')) or next(iter(pipelines.values()), {})
    ran = [item for item in pipeline.get('stages') or []
           if str(item.get('id', '')).startswith('stage-') and item.get('status') != 'skipped']
    if not ran or 'id' not in pipeline:
        return {}
    return api(f'{CNB}/build/logs/stage/{sn}/{pipeline["id"]}/{ran[-1]["id"]}', missing=True) or {}


def rate_limited(stage):
    return re.search(r'LLM request error.*\b429\b', str(stage.get('error') or '')) is not None


def final_report(stage, request):
    """Return the closing message of a run that ended normally, if it holds this request's conclusion; else ''.

    A reviewer sometimes writes its report as that message and never posts it, and a newly summoned one cannot see it.
    """
    lines = [ANSI.sub('', str(line)) for line in stage.get('content') or []]
    finishes = [i for i, line in enumerate(lines) if re.match(r'Master\[agent\]\[\d+\] \S+ \S+ finish with ', line)]
    if not finishes or ' finish with stop' not in lines[finishes[-1]]:
        return ''
    end = finishes[-1]
    start = next((i for i in range(end - 1, -1, -1) if re.fullmatch(r'Master\[agent\]\[\d+\] \S+ \S+ started', lines[i])),
                 None)
    if start is None:
        return ''
    report = '\n'.join(AGENT_LINE.sub('', line, count=1) for line in lines[start + 1:end]).strip()
    verdicts = re.findall(r'^FLCLASH_REVIEW (\{[^\r\n]+\})\s*$', report, re.M)
    try:
        return report if verdicts and json.loads(verdicts[-1]).get('request') == identity(request) else ''
    except ValueError:
        return ''


def quoted(text):
    """Quote log text for an owner-authored comment, where it must not summon anyone or read as a signed marker."""
    if len(text) > EXCERPT_CHARS:
        text = '（前面已截断）\n' + text[-EXCERPT_CHARS:]
    return '\n'.join('> ' + line for line in text.replace('@', '＠').replace('<!--', '＜!--').splitlines())


def _resend_body(request, role, comments, sn, report):
    link = f'日志：https://cnb.cool/{POLICY["cnb"]}/-/build/logs/{sn}\n\n' if sn else '\n\n'
    head = f'上次 {role} 的召唤结束时本 Issue 里没有它的报告，自动补召。{link}@{POLICY["cnb"]}({role}) '
    tail = ('合并相关查询，不重复搜索已确认的信息，不sleep、不轮询另一位报告，不自动召唤任何 NPC。'
            '报告必须用 `cnb issues comment` 发到本 Issue，只写在最终回复里门禁读不到。'
            '未完成必须明确说明，不回复 OK，不合并、不发布、不忽略测试或告警。')
    if report:
        sample = json.dumps({'request': identity(request), 'verdict': 'pass', 'blockers': 0})
        return (head + '下面是控制器从你上次运行的构建日志里摘出的最终回复，每行前加了 `> `。它没有发到本 Issue。'
                '这段摘录不是你的发言，门禁不采信。核对它针对的还是固定 '
                f'head `{request["head"]}`、结论与证据相符，然后把报告发到本 Issue，结论行单独一行、不带 `> `，'
                f'例如 `FLCLASH_REVIEW {sample}`（无阻断才用 pass）；不能确认就用 block。不用发进度评论。'
                + EVIDENCE_RULES + budget_text(BUDGET['resend']) + tail + '\n\n' + quoted(report))
    budget = BUDGET['reconsider'] if _owner_comment(comments, _checkpoint(request, role, 'reconsider')) else BUDGET['review']
    return head + review_instruction(request, budget) + tail


def _since(stamp, now):
    import datetime
    return (now - datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds()


def _last_summon(issue, comments, role):
    mention = f'@{POLICY["cnb"]}({role})'
    stamps = [item.get('created_at', '') for item in comments if owner(item) and mention in item.get('body', '')]
    if mention in issue.get('body', ''):
        stamps.append(issue.get('created_at', ''))
    return max(stamps, default='')


def _held(request):
    """True while the owner holds the requirement this review's pull implements. Only automation/req-* can be held."""
    pull = api(f'{endpoint(request["platform"])}/pulls/{request["number"]}')
    return bool(pause.paused('branch', pull['head']['ref'].removeprefix('refs/heads/')))


def recover_review(issue, request, comments, now, room):
    """Summon again each reviewer whose latest summon has ended without a report; return how many were sent.

    A summon counts as ended when its run finished, or when it is overdue and no run ever started. A run still going
    is only stopped once overdue, never summoned over; the next pass then finds it finished. No report never passes.
    A HOLD stops all of it, so nothing is read, stopped or posted, and the deadlines simply resume after RELEASE.
    """
    latest = role_reports(request, issue, comments)
    attempts = latest_attempts(issue, comments)
    sent = 0
    for role in ROLES:
        _, context, attempted = attempts.get(role, (None, {}, ''))
        since = max(attempted, _last_summon(issue, comments, role))
        # Reports are matched by role_reports itself, so a report for another request is not one for this.
        if (latest.get(role) == 'pass' or not since
                or role_reports(request, {'created_at': since}, comments).get(role)):
            continue
        # Read only when there is something to act on: this costs the pull and the requirement's comments.
        if _held(request):
            print(f'Review #{issue["number"]} waits: its requirement is on HOLD')
            return sent
        overdue = _since(since, now) > (REVIEW_SECONDS if since == issue.get('created_at') else FOLLOWUP_SECONDS)
        sn = context.get('sn', '') if attempted == since else ''
        stage = {}
        if re.fullmatch(r'cnb-[a-z0-9-]+', sn):
            build = api(f'{CNB}/build/status/{sn}')
            if build['status'] not in FINISHED:
                if overdue:
                    api(f'{CNB}/build/stop/{sn}', 'POST')
                    print(f'Stopped overdue {role} run {sn} on #{issue["number"]}')
                continue
            stage = _final_stage(sn, build, context)
        elif not overdue:
            continue
        ended = stage.get('endTime')
        quiet = now.timestamp() - ended / 1000 if ended else None
        if quiet is not None and quiet < SETTLE_SECONDS:
            continue
        key = hashlib.sha256(f'{issue["number"]}:{identity(request)}:{role}'.encode()).hexdigest()
        retries = sum(has_marker([item], key, 'retry') for item in comments)
        if retries >= RESEND_LIMIT:
            if not has_marker(comments, key, 'stopped'):
                comment(issue['number'], recovery_marker(key, 'stopped')
                        + f'\n\n{role} 连续 {retries + 1} 次召唤都没有交付报告，自动补召已用完，未作通过判定。'
                        '等待维护者处理，规程见 `.agents/rules.md` 的 Reviewer non-delivery。')
            continue
        if rate_limited(stage) and quiet is not None and quiet < RATE_LIMIT_SECONDS * 2 ** retries:
            continue
        if sent >= room:
            continue
        comment(issue['number'], recovery_marker(key, 'retry') + '\n\n'
                + _resend_body(request, role, comments, sn, final_report(stage, request)))
        sent += 1
    return sent


def recover_task(issue, now, room):
    """One bounded retry for a failed task that is not a review; return how many were sent."""
    spec = task(issue)
    if not spec:
        return 0
    scope, roles, work_mode, instruction = spec
    comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
    if work_mode:
        for item in sorted(comments, key=lambda c: (c.get('created_at', ''), int(c['id']))):
            revision = re.search(r'<!-- security-work-requested ' + re.escape(spec[0])
                                 + r':([a-f0-9]{16}) -->', item.get('body', ''))
            if owner(item) and revision:
                scope = spec[0] + ':' + revision[1]
    sent = 0
    for role, (state, context, started) in latest_attempts(issue, comments).items():
        sn = context.get('sn', '')
        if role in roles and not work_mode and hung(state, started, now) and re.fullmatch(r'cnb-[a-z0-9-]+', sn):
            # A hung run blocks recovery forever; stopping it turns it into an error the next pass retries.
            if api(f'{CNB}/build/status/{sn}')['status'] not in ('success', 'error', 'failure', 'cancel'):
                api(f'{CNB}/build/stop/{sn}', 'POST')
                print(f'Stopped hung {role} run {sn} on #{issue["number"]}')
            continue
        if role not in roles or state not in ('error', 'failure'):
            continue
        if any(c.get('author', {}).get('username') == f'{POLICY["cnb"]}({role})'
               and c.get('author', {}).get('is_npc') is True
               and c.get('created_at', '') >= started and not progress(c.get('body', '')) for c in comments):
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
        if sent >= room or not re.fullmatch(r'cnb-[a-z0-9-]+', sn):
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
        sent += 1
    return sent


def recover(now=None):
    import datetime
    now = now or datetime.datetime.now(datetime.timezone.utc)
    sent, failed = 0, []
    for summary in pages(f'{CNB}/issues?state=open'):
        try:
            issue = api(f'{CNB}/issues/{summary["number"]}')
            if issue.get('state') != 'open':
                continue
            request = None if str(issue.get('title', '')).startswith('[需求]') else request_from(issue)
            if request:
                comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
                sent += recover_review(issue, request, comments, now, MAX_PER_PASS - sent)
            else:
                sent += recover_task(issue, now, MAX_PER_PASS - sent)
        except Exception as error:
            failed.append(str(summary['number']))
            print(f'Recovery of #{summary["number"]} failed, continuing: {type(error).__name__}: {error}', flush=True)
    if failed:
        raise RuntimeError('Recovery failed on issues ' + ', '.join(failed))


if __name__ == '__main__':
    recover()
