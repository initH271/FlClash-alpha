import contextlib
import hashlib
import json
import re
import subprocess
import sys
import time

from control import (CI_GRACE, CNB, FETCH_TIMEOUT, GH, GIT_TIMED_OUT, POLICY, all_issues, api, check_name, git,
                     pages, sign, verify)
from review_evidence import describe, repository

CONTEXT = 'FlClash/paired-review'
ROLES = ('审查助手', 'GLM复核助手')
GLM = ROLES[1]
# Past either limit GLM gets one issue per file group; it rarely finished a larger diff in one summon.
SHARD_FILES, SHARD_LINES = 6, 350
SHARDS = re.compile(r'<!-- flclash-review-shards ([\d,]+) -->')
SHARD_NOTICE = re.compile(r'GLM复核助手按文件分片审核：[^\n]*\n<!-- flclash-review-shards [\d,]+ -->')
# The main.pull_request pipelines in .cnb.yml, and the only checks that gate a review. The paired review
# gate runs under pull_request.target and waits for the review itself, so it must never be listed here.
CI_PIPELINES = ('Dependency vulnerability gate', 'Automation unit tests', 'Go dependency regression tests',
                'Flutter and Android requirement tests', 'Rust dependency regression tests')
NOTICE = re.compile(r'<!-- flclash-review-notice (\d+) -->')
REUSE = re.compile(r'<!-- flclash-review-reuse (\{[^\r\n]+\}) -->')
SNAPSHOT = re.compile(r'<!-- flclash-review-snapshot (\{[^\r\n]+\}) -->')
# Titles the controller gives issues that are not a review of the pull being looked up.
ELSEWHERE = re.compile(r'\[PR审核\] (?:GitHub|CNB) #\d+：|\[(?:需求|安全修复|上游升级|构建待处理)\] ')
CI_GRACE_SECONDS = 80 * 60
# The controller's own job in reviews.yaml. It reports on the PR head and is always running while it reads CI.
CONTROLLER_CHECK = 'review'
CHECK_RUNNING = ('queued', 'in_progress', 'waiting', 'requested', 'pending')
# reusable's answer while a same-patch reuse waits for CI: open nothing and write nothing on this run.
WAITING = object()
# Tool calls a reviewer may spend per summon. A budget written only in the prompt has not
# stopped GLM, so progress is also posted per event instead of relying on the count alone.
BUDGET = {'review': 40, 'reconsider': 12}
PROGRESS = 'FLCLASH_PROGRESS'
EVIDENCE_RULES = (
    '每条阻断项都要附原文：用 `git show <head>:<路径>` 读出，写成 `路径:起止行号`，下面原样粘贴不超过 15 行，不改写。'
    '没有原文行号的阻断只能列为观察项，不计入 blockers。\n'
    '「上游原样」文件：和升级目标上游 tag 里同一路径的 blob 相同（`git rev-parse <tag>:<路径>` 等于 '
    '`git rev-parse <head>:<路径>`）的文件不是本 fork 的改动，只能写成观察项，不能作为阻断，也不计入 blockers。\n'
    '只审下面列出的 diff 文件和行范围；不要去翻历史 issue，前几轮的阻断由控制器列在本条里。\n')
CHECKLIST = (
    '审核清单（每项都在报告里写结论）：\n'
    '1. 逐条对照验收标准原文，每条写 pass / block / 未审到，不用自己的转述代替原文。\n'
    '2. 单测的调用参数和生产调用一致：测试替身和被替换函数的签名、返回类型一致。\n'
    '3. 单测不联网。\n'
    '4. 不要 mock 掉被测对象本身。\n')


# What one reconcile has already read. It exists only inside reconcile, whose writes all go through _write, so a
# caller that writes through control.api between two reads, as the requirement loop does, always reads afresh.
_round = None


@contextlib.contextmanager
def _one_round():
    global _round
    outer, _round = _round, {'rows': None, 'issues': {}, 'failed_fetches': set()}
    try:
        yield
    finally:
        _round = outer


def _write(url, method, data):
    """Send a write and drop what it made stale. A comment leaves the issue list's title and state as they were."""
    found = api(url, method, data)
    touched = re.fullmatch(re.escape(CNB) + r'/issues(?:/(\d+)(/comments)?)?', url)
    if _round is None or not touched:
        return found
    _round['issues'].pop(touched[1], None)
    if not touched[1]:
        # A new issue changes no other row, so this list stays good for the next pull in the round.
        if _round['rows'] is not None:
            _round['rows'].insert(0, dict(found))
    elif not touched[2]:
        _round['rows'] = None
    return found


def _issue(number, missing=False):
    """Read one issue with its body. Works for a closed issue too; a 404 is never remembered."""
    number = str(number)
    if _round is not None and number in _round['issues']:
        return _round['issues'][number]
    url = f'{CNB}/issues/{number}'
    found = api(url, missing=True) if missing else api(url)
    if _round is not None and found:
        _round['issues'][number] = found
    return found


def _issue_rows():
    """The issue list, open first. Its rows have a title and state but no body, so they cannot verify anything."""
    if _round is None:
        return all_issues()
    if _round['rows'] is None:
        _round['rows'] = list(all_issues())
    return _round['rows']


def _titled(request):
    """List rows that can hold a review of this pull, open or closed, without reading any other issue.

    Only a title that says it is something else rules a row out: the controller's own titles for another pull or
    another kind of issue. A row with a title anyone made up, or none, is still read, so a review renamed by hand
    stays found. This only narrows the search; the signed body still decides, and find_request also follows the
    pull's notices for a review renamed to look like one of those.
    """
    prefix = title_prefix(request)
    return (row for row in _issue_rows()
            if (title := str(row.get('title') or '')).startswith(prefix) or not ELSEWHERE.match(title))


def _noticed(request):
    """Review issue numbers the pull's own comments point at, in the order they were posted."""
    github = request['platform'] == 'github'
    path = (f'{GH}/issues/{request["number"]}/comments' if github
            else f'{CNB}/pulls/{request["number"]}/comments')
    return list(dict.fromkeys(n for c in pages(path, size_key='per_page' if github else 'page_size')
                              for n in noticed_reviews(str(c.get('body', '')))))


def budget_text(n):
    return (f'工具调用预算：本次最多 {n} 次，其中 1 次留给发布最终报告，取证和进度评论合计最多 {n - 1} 次。'
            f'按事件发进度：每审完一个文件或一组验收条目，就在本 Issue 追加一条首行为 `{PROGRESS}` 的进度评论，'
            '写已审范围、已发现的阻断和下一步，不要等到最后。'
            f'用到第 {n - 2} 次时停止取证，先发一条首行为 `{PROGRESS}` 的「未完成」状态评论，写明审到哪里、还差什么，'
            '再用最后一次发布报告；没核实的写进「未验证项」并使用 block。'
            '只写在最终回复里的文字不会出现在 Issue 里，门禁读不到，等于没有审核。\n')


def progress(body):
    """A progress or unfinished note: first line is the marker and it carries no machine verdict."""
    return body.lstrip().startswith(PROGRESS) and not re.search(r'^FLCLASH_REVIEW ', body, re.M)


def scope(platform, pull):
    return {'platform': platform, 'number': str(pull['number']),
            'base': pull['base']['sha'], 'head': pull['head']['sha']}


def unsharded(request):
    return {key: value for key, value in request.items() if key != 'shard'}


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
        if progress(comment.get('body', '')):
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


def result(request, issue, comments, parts=None):
    """With shard parts, GLM passes only when every open shard passed; a blocked shard fails it, open or closed.

    Any other missing or closed shard leaves GLM pending until ensure_request replaces it, and a pass on a
    closed shard does not count. The main issue never summons GLM, so `parts` of [] must stay here and not
    fall back to reports on the main issue.
    """
    if issue['state'] != 'open':
        return 'failure'
    if reused_from(request, issue):
        return 'success'
    latest = role_reports(request, issue, comments)
    if parts is not None:
        latest.pop(GLM, None)
        if shards_blocked(parts):
            latest[GLM] = 'block'
        elif shards_complete(parts) and all(role_reports(part, found, notes).get(GLM) == 'pass'
                                            for part, found, notes in parts if found['state'] == 'open'):
            latest[GLM] = 'pass'
    if any(value in ('block', 'malformed') for value in latest.values()):
        return 'failure'
    return 'success' if all(latest.get(role) == 'pass' for role in ROLES) else 'pending'


def find_request(request, signed=True):
    """Return the issue holding this exact request, or None. Closed ones count: closing a review cannot shed it.

    A miss, the usual case for a new head, costs the rows titled for this pull and its notices, however many other
    issues exist.
    """
    seen = set()
    for row in _titled(request):
        seen.add(str(row['number']))
        detail = _issue(row['number'])
        if request_from(detail, signed) == request:
            return detail
    for number in _noticed(request):
        detail = None if number in seen else _issue(number, missing=True)
        if detail and request_from(detail, signed) == request:
            return detail
    return None


def state(request, signed=True):
    issue = find_request(request, signed)
    if issue is None:
        return 'pending'
    return result(request, issue, list(pages(f'{CNB}/issues/{issue["number"]}/comments')),
                  shard_parts(request, issue, signed))


def shard_parts(request, issue, signed=True):
    """Return (shard request, issue, comments) for each verified GLM shard the full review lists.

    Closed shards stay in the list for their blocker quotes. None means the review has no shard marker.
    """
    match = SHARDS.search(issue.get('body', ''))
    if not match:
        return None
    parts = []
    for number in dict.fromkeys(match[1].split(',')):
        detail = _issue(number, missing=True)
        part = request_from(detail, signed) if detail else None
        if isinstance(part, dict) and isinstance(part.get('shard'), dict) and unsharded(part) == request:
            parts.append((part, detail, list(pages(f'{CNB}/issues/{number}/comments'))))
    return parts


def shards_blocked(parts, state=None):
    """True when a shard, or only those in `state`, holds a GLM block or malformed report."""
    return any(role_reports(part, found, notes).get(GLM) in ('block', 'malformed')
               for part, found, notes in parts if state in (None, found['state']))


def shards_complete(parts):
    """True when the open shards cover every index of one grouping."""
    live = [part['shard'] for part, found, _ in parts if found['state'] == 'open']
    totals = {shard['total'] for shard in live}
    return len(totals) == 1 and {shard['index'] for shard in live} == set(range(1, totals.pop() + 1))


def title_prefix(request):
    platform = 'GitHub' if request['platform'] == 'github' else 'CNB'
    return f'[PR审核] {platform} #{request["number"]}：'


def review_title(request, title):
    description = ' '.join(title.split()).replace('@', '＠')[:100] or '审核代码变更'
    return title_prefix(request) + description


def requirement_brief(pull):
    ref = str((pull.get('head') or {}).get('ref', '')).removeprefix('refs/heads/')
    match = re.fullmatch(r'automation/req-(\d+)', ref)
    if not match:
        return ''
    # Imported lazily: requirements imports this module at load time.
    from requirements import owner, parse
    issue = _issue(match[1], missing=True)
    if not issue or not owner(issue):
        return ''
    acceptance = parse(issue.get('body', ''))['acceptance']
    if not acceptance:
        return ''
    return (f'本 PR 实现需求 #{match[1]}：https://cnb.cool/{POLICY["cnb"]}/-/issues/{match[1]}\n'
            '逐条核对下列验收标准。任何一条不能从实际 diff 确认已满足，或开发助手在该需求 issue '
            '最新的阶段报告里写明未满足、未完成，都必须判 block，并在阻断项里写明是哪一条。'
            'CI 通过不等于验收通过。\n' + acceptance + '\n\n')


def hunks(request):
    """Map each changed path to its head line ranges and line counts, or None when git cannot diff."""
    found = git('diff', '-U0', '--no-color', '--no-ext-diff', f'{request["base"]}...{request["head"]}', check=False)
    if found.returncode:
        return None
    files, path, header = {}, '', False
    for line in found.stdout.splitlines():
        if line.startswith('diff --git '):
            path, header = line.split(' b/', 1)[-1], True
            files[path] = {'ranges': [], 'added': 0, 'removed': 0}
        elif header and line.startswith('+++ /dev/null'):
            files[path]['ranges'].append('整个文件删除')
        elif header and line.startswith('@@'):
            header = False
        if line.startswith('@@') and path and '整个文件删除' not in files[path]['ranges']:
            start, count = re.match(r'@@ -\S+ \+(\d+)(?:,(\d+))? @@', line).groups()
            start, count = int(start), 1 if count is None else int(count)
            files[path]['ranges'].append(f'删除于 {start} 行后' if count == 0 else
                                         str(start) if count == 1 else f'{start}-{start + count - 1}')
        elif not header and path and line[:1] in ('+', '-'):
            files[path]['added' if line[0] == '+' else 'removed'] += 1
    return files


def shards(request):
    """Group an oversized diff for GLM: directories kept together, each group within both limits.

    A file over the line limit is a group of its own. An empty list keeps the single full review.
    """
    files = hunks(request) or {}
    sizes = {path: item['added'] + item['removed'] for path, item in files.items()}
    if len(sizes) <= SHARD_FILES and sum(sizes.values()) <= SHARD_LINES:
        return []
    groups, lines = [[]], 0
    for path in sorted(sizes, key=lambda name: (name.rpartition('/')[0], name)):
        if groups[-1] and (len(groups[-1]) == SHARD_FILES or lines + sizes[path] > SHARD_LINES):
            groups.append([])
            lines = 0
        groups[-1].append(path)
        lines += sizes[path]
    if len(groups) == 1:
        return []
    return [{'index': i, 'total': len(groups), 'paths': paths} for i, paths in enumerate(groups, 1)]


def diff_scope(request, limit=60, paths=None):
    """List each changed file, or only `paths`, with the head line ranges of its hunks."""
    files = hunks(request)
    if files is None:
        return '控制器取不到 diff 的行范围，按上面的文件清单审核，并在报告里写明。\n\n'
    files = {name: item for name, item in files.items() if paths is None or name in paths}
    rows = [f'- `{name}`：{"、".join(item["ranges"]) or "无文本行（二进制或仅改权限）"}'
            f'（+{item["added"]}/−{item["removed"]}）' for name, item in list(files.items())[:limit]]
    if len(files) > limit:
        rows.append(f'- 另有 {len(files) - limit} 个文件未列出，覆盖不足必须写明。')
    return ('本次 diff 的文件清单与 head 行范围（控制器从 merge-base...head 生成）：\n'
            + '\n'.join(rows or ['- 没有文件改动。']) + '\n\n')


def _blocking(body):
    for line in re.findall(r'^FLCLASH_REVIEW (\{[^\r\n]+\})\s*$', body, re.M):
        try:
            report = json.loads(line)
        except ValueError:
            continue
        if report.get('verdict') != 'pass' or report.get('blockers') != 0:
            return True
    return False


def prior_blockers(request, keep=4):
    """Quote the blocking reports on earlier heads of the same pull, so reviewers need not read old issues."""
    quotes = []
    for number in _noticed(request):
        issue = _issue(number, missing=True)
        old = request_from(issue) if issue else None
        if not old or old == request:
            continue
        notes = list(pages(f'{CNB}/issues/{number}/comments'))
        for comment in notes + [row for _, _, rows in shard_parts(old, issue) or () for row in rows]:
            author = comment.get('author') or {}
            role = next((r for r in ROLES if author.get('username') == f'{POLICY["cnb"]}({r})'), None)
            if role and author.get('is_npc') is True and _blocking(comment.get('body', '')):
                text = re.sub(r'^FLCLASH_REVIEW .*$\n?', '', comment['body'], flags=re.M).strip()
                quotes.append(f'#{number} {role}（head `{old["head"][:12]}`）：\n' + text[:1200].replace('@', '＠'))
    if not quotes:
        return ''
    return ('前几轮的阻断清单（控制器从旧审核 issue 摘出）。先逐条核对它们在本 head 是否已修好，再审其余改动：\n'
            + '\n\n'.join(quotes[-keep:]) + '\n\n')


def ensure_request(request, title, brief=''):
    issue = find_request(request)
    display_title = review_title(request, title)
    platform, number = request['platform'], request['number']
    url = (f'https://github.com/{POLICY["github"]}/pull/{number}' if platform == 'github'
           else f'https://cnb.cool/{POLICY["cnb"]}/-/pulls/{number}')
    if issue:
        if issue['title'] != display_title:
            _write(f'{CNB}/issues/{issue["number"]}', 'PATCH', {'title': display_title})
        return heal_shards(request, issue, display_title, url)
    groups = shards(request)
    numbers = ensure_shards(request, groups, display_title, url) if groups else []
    marker = '<!-- flclash-pr-review ' + json.dumps(sign(request)) + ' -->'
    sample = json.dumps({'request': identity(request), 'verdict': 'pass', 'blockers': 0})
    body = (f'PR 自动结对审核：{url}\n\n{marker}\n\n' + brief + describe(request) + '\n'
            + diff_scope(request) + prior_blockers(request) + EVIDENCE_RULES + CHECKLIST
            + budget_text(BUDGET['review']) + '\n'
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
            + (shard_notice(numbers) + '\n\n' if numbers else '')
            + '\n\n'.join(f'@{POLICY["cnb"]}({r}) 请独立审核上述 PR。'
                          for r in (ROLES[:1] if numbers else ROLES)))
    issue = _write(f'{CNB}/issues', 'POST', {'title': display_title,
                'body': body, 'work_mode': False, 'assignees': [POLICY['approver']]})
    body = (f'结对审核： https://cnb.cool/{POLICY["cnb"]}/-/issues/{issue["number"]}\n'
            f'base `{request["base"]}` / head `{request["head"]}`。两位审核者完成且无阻断问题后检查才通过。'
            + (f'\n<!-- flclash-review-notice {issue["number"]} -->' if platform == 'cnb' else ''))
    # existing_review reads the notice back from this same pull comment endpoint.
    _write(f'{GH}/issues/{number}/comments' if platform == 'github' else f'{CNB}/pulls/{number}/comments',
           'POST', {'body': body})
    return issue


def shard_notice(numbers):
    links = '、'.join(f'https://cnb.cool/{POLICY["cnb"]}/-/issues/{n}' for n in numbers)
    return (f'GLM复核助手按文件分片审核：{links}。本 Issue 只召唤审查助手，全部分片通过才算 GLM 通过。\n'
            f'<!-- flclash-review-shards {",".join(numbers)} -->')


def heal_shards(request, issue, title, url):
    """Replace missing or closed shards of an open review, as a deleted main review is reopened on the next run.

    A closed shard is left closed, like any manual closure, and surviving shards keep their reports. Closing a
    shard cannot shed its block: nothing is replaced then, and GLM stays blocked until the head changes. A pass
    on a closed shard is reviewed again. With no groups (git cannot read the diff) nothing changes and GLM stays
    pending for the next run to retry.
    """
    parts = shard_parts(request, issue)
    if (parts is None or issue['state'] != 'open' or shards_complete(parts)
            or shards_blocked(parts, 'closed')):
        return issue
    groups = shards(request)
    if not groups:
        return issue
    notice = shard_notice(ensure_shards(request, groups, title, url))
    body = SHARD_NOTICE.sub(lambda _: notice, issue['body'], count=1)
    _write(f'{CNB}/issues/{issue["number"]}', 'PATCH', {'body': body})
    return dict(issue, body=body)


def ensure_shards(request, groups, title, url):
    """Open one GLM-only issue per file group, reusing any open one left by an earlier run."""
    known = {}
    for item in _titled(request):
        if item.get('state', 'open') != 'open':
            continue
        detail = _issue(item['number'])
        part = request_from(detail)
        if (detail['state'] == 'open' and isinstance(part, dict) and part.get('shard') in groups
                and unsharded(part) == request):
            known.setdefault(part['shard']['index'], str(detail['number']))
    for group in groups:
        if group['index'] in known:
            continue
        part = dict(request, shard=group)
        sample = json.dumps({'request': identity(part), 'verdict': 'pass', 'blockers': 0})
        body = (f'PR 自动审核 GLM 分片 {group["index"]}/{group["total"]}：{url}\n\n'
                '<!-- flclash-pr-review ' + json.dumps(sign(part)) + ' -->\n\n'
                f'本 Issue 只审下列 {len(group["paths"])} 个文件，其余文件在其他分片里审；全量 diff 和验收标准'
                '由审查助手在主审核 Issue 核对。清单第 1 项只回答本组文件涉及的验收条目，'
                '与本组无关的条目写「不在本组」，不因此判 block。\n'
                + diff_scope(part, paths=group['paths']) + EVIDENCE_RULES + CHECKLIST
                + budget_text(BUDGET['review']) + '\n'
                f'固定 base `{request["base"]}`，head `{request["head"]}`。'
                '只读；不运行 PR 中的代码、不安装依赖、不编译、不修改代码、不合并或发版，不召唤其他 NPC。'
                '提交不匹配、无法读取或审核未完成时不得通过。\n\n'
                '报告末尾必须单独一行输出以下机器结论（不要放入代码块）：\n'
                f'FLCLASH_REVIEW {sample}\n'
                '只有审完本组且没有阻断问题才能使用 pass / blockers=0；'
                '否则使用 verdict=block，blockers 为正整数。request 原样保留。\n\n'
                f'@{POLICY["cnb"]}({GLM}) 请审核本分片。')
        known[group['index']] = str(_write(f'{CNB}/issues', 'POST', {
            'title': f'{title}（GLM 分片 {group["index"]}/{group["total"]}）', 'body': body,
            'work_mode': False, 'assignees': [POLICY['approver']]})['number'])
    return [known[group['index']] for group in groups]


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
            _write(f'{CNB}/issues/{issue["number"]}/comments', 'POST', {'body': body, 'work_mode': False})
            continue
        marker = _checkpoint(request, role, 'reconsider')
        paths = (request.get('shard') or {}).get('paths')
        body = (marker + '\n\n' + describe(request) + diff_scope(request, paths=paths) + EVIDENCE_RULES
                + budget_text(BUDGET['reconsider'])
                + f'@{POLICY["cnb"]}({role}) 报告格式不完整或双方结论有分歧，执行唯一一次有界复核。'
                '只核对实际差异和现有阻断，明确纠正已证实的事实错误。'
                '不为了达成共识而通过；真实阻断保留，不能确认则报告block。'
                '不等待另一位、不自行召唤。报告最后单独一行输出机器结论（无阻断时才使用下例）：\n'
                + 'FLCLASH_REVIEW ' + sample)
        _write(f'{CNB}/issues/{issue["number"]}/comments', 'POST', {'body': body, 'work_mode': False})


def _number(item):
    return str(item['number'])


def _since(stamp):
    import datetime
    return time.time() - datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()


def noticed_reviews(body):
    """Return the review issue numbers a pull comment points at, marker first, then the issue link."""
    link = re.escape(f'https://cnb.cool/{POLICY["cnb"]}/-/issues/') + r'(\d+)'
    # Notices written before the marker existed carry only the link.
    found = NOTICE.findall(body) + re.findall(r'结对审核：\s*' + link, body)
    return list(dict.fromkeys(found))


def existing_review(pull):
    """Return the review issue already opened for this base/head without listing every issue."""
    request = scope('cnb', pull)
    for summary in pages(f'{CNB}/pulls/{pull["number"]}/comments', size_key='page_size'):
        for number in noticed_reviews(str(summary.get('body', ''))):
            detail = _issue(number, missing=True)
            if detail and request_from(detail) == request:
                return detail
    return None


def ci_state(checks):
    """Return pending, failure or success over the five main.pull_request pipelines only."""
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
    # With no status at all there is still a start: the PR itself. `/pulls/{n}` carries no time,
    # so `reconcile` keeps the list entry's `created_at` for this.
    started = min(stamps) if stamps else pull.get('created_at')
    if not started:
        print(f'cnb PR #{_number(pull)}: waiting for CI (no PR created_at)')
        return True, False
    if _since(started) < CI_GRACE_SECONDS:
        print(f'cnb PR #{_number(pull)}: waiting for CI')
        return True, False
    print(f'cnb PR #{_number(pull)}: CI unsettled after 80m, review opened')
    return False, True


def unsettled_brief(pull):
    """Name the pipelines a review opened past the grace could not wait for."""
    from wake import SETTLED
    statuses = (api(f'{CNB}/pulls/{pull["number"]}/commit-statuses') or {}).get('statuses') or []
    if not statuses:
        return ('开审时这个 head 没有任何 CI 状态，没有 CI 证据；所有条目按未验证处理，'
                '不能因为 CI 没跑完就通过。\n\n')
    states = {}
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
    marks = sorted((item for item in statuses if check_name(item) == CI_GRACE),
                   key=lambda item: item.get('created_at') or '')
    current = marks[-1].get('state') if marks else ''
    if ci_state({'statuses': statuses}) in ('pending', 'failure'):
        if current != 'failure':
            _write(f'{CNB}/statuses/{pull["head"]["sha"]}', 'POST', {
                'state': 'failure', 'context': CI_GRACE,
                'description': 'Review opened before CI settled; merge waits for every pipeline'})
    elif current and current != 'success':
        _write(f'{CNB}/statuses/{pull["head"]["sha"]}', 'POST', {
            'state': 'success', 'context': CI_GRACE, 'description': 'Every pull_request pipeline has settled'})


def patch_id(base, head):
    """Fingerprint the pull's own change, merge-base..head, which a base that only moves forward leaves alone."""
    found = git('merge-base', base, head, check=False)
    if found.returncode:
        return None
    diff = git('diff', '--binary', '--no-renames', '--no-color', '--no-ext-diff',
               found.stdout.strip(), head, check=False)
    if diff.returncode or not diff.stdout.strip():
        return None
    out = subprocess.run(['git', 'patch-id', '--stable'], input=diff.stdout,
                         text=True, capture_output=True, check=False)
    return out.stdout.split()[0] if not out.returncode and out.stdout.strip() else None


def _owner_payload(pattern, item):
    author = item.get('author') or {}
    match = pattern.search(item.get('body', ''))
    if not match or author.get('username') != POLICY['approver'] or author.get('is_npc') is not False:
        return None
    try:
        return verify(json.loads(match[1]))
    except (ValueError, KeyError, TypeError):
        return None


def reused_from(request, issue):
    payload = _owner_payload(REUSE, issue)
    return payload if isinstance(payload, dict) and payload.get('request') == identity(request) else None


def _record(request, comments):
    """The latest signed conclusion the controller recorded on a review Issue, or None."""
    record = None
    for comment in sorted(comments, key=lambda c: (c.get('created_at', ''), str(c.get('id', '')))):
        payload = _owner_payload(SNAPSHOT, comment)
        if isinstance(payload, dict) and payload.get('request') == identity(request):
            record = payload
    return record


def snapshot(request, comments):
    """The latest gate conclusion the controller recorded on a review Issue: pass, block or None."""
    return (_record(request, comments) or {}).get('verdict')


def _shard_numbers(parts):
    return sorted(str(found['number']) for _, found, _ in parts)


def remember(request, issue, comments, status, parts=None):
    """Record each change of a review's gate conclusion, so a later base can reuse it after the Issue closes.

    `status` already reads the shards when `parts` is given. The record names them, because such a pass rests
    on their reports and there is none from GLM on the main issue.
    """
    latest = snapshot(request, comments)
    verdict = {'success': 'pass', 'failure': 'block'}.get(status, 'block' if latest == 'pass' else None)
    if verdict is None or verdict == latest:
        return
    payload = {'request': identity(request), 'verdict': verdict}
    note = ''
    if parts is not None:
        payload['glm_shards'] = _shard_numbers(parts)
        note = f'（GLM 分片：{"、".join(payload["glm_shards"]) or "无"}）'
    _write(f'{CNB}/issues/{issue["number"]}/comments', 'POST', {'work_mode': False, 'body': (
        f'<!-- flclash-review-snapshot {json.dumps(sign(payload))} -->\n门禁结论记录：{verdict}{note}')})


def _fresh_ci(pull, since):
    """success once every pull_request pipeline passed in a run newer than the reused review; else pending or failure.

    Passes older than the review have not run on this base yet, so they read as pending, not as a verdict.
    """
    statuses = (api(f'{CNB}/pulls/{pull["number"]}/commit-statuses') or {}).get('statuses') or []
    state = ci_state({'statuses': statuses})
    if state != 'success':
        return state
    newest = {}
    for item in statuses:
        newest[check_name(item)] = max(newest.get(check_name(item), ''), item.get('created_at') or '')
    return 'success' if all(newest.get(name, '') > since for name in CI_PIPELINES) else 'pending'


def _github_ci(head):
    """success when a check besides the controller and its gate exists and all passed; else pending or failure.

    A head with no such check yet reads as pending, since its workflows may not have registered.
    """
    runs = api(f'{GH}/commits/{head}/check-runs?per_page=100') or {}
    rows = runs.get('check_runs') or []
    if runs.get('total_count', len(rows)) > len(rows):
        return 'failure'
    statuses = (api(f'{GH}/commits/{head}/status') or {}).get('statuses') or []
    found = ([run.get('conclusion') if run.get('status') == 'completed' else run.get('status')
              for run in rows if run.get('name') != CONTROLLER_CHECK]
             + [item.get('state') for item in statuses if item.get('context') != CONTEXT])
    counted = [state for state in found if state not in ('skipped', 'neutral')]
    if not counted or any(state in CHECK_RUNNING for state in counted):
        return 'pending'
    return 'success' if all(state == 'success' for state in counted) else 'failure'


def _fetch_rounds(request, rounds):
    """Bring every commit a reuse compares into this checkout, by sha; True when they are all here.

    The controller checks out main, so a CNB or fork head, or a head since replaced by a force push, may be missing.
    """
    wanted = dict.fromkeys(sha for item in [request] + [old for old, _ in rounds] for sha in (item['base'], item['head']))
    missing = [sha for sha in wanted if git('cat-file', '-e', f'{sha}^{{commit}}', check=False).returncode]
    if not missing:
        return True
    # Within a round, do not ask again for commits that just failed, nor wait again on a remote that just hung.
    remote, failed = repository(request), _round['failed_fetches'] if _round is not None else set()
    if remote in failed or (remote, *missing) in failed:
        return False
    code = git('fetch', '--no-tags', remote, *missing, check=False, timeout=FETCH_TIMEOUT).returncode
    if code:
        failed.add(remote if code == GIT_TIMED_OUT else (remote, *missing))
    return code == 0


def _scope_age(request):
    """Seconds since the later of the base and head commits, or None when that cannot be read or lies in the future."""
    found = git('show', '-s', '--format=%ct', request['base'], request['head'], check=False)
    stamps = found.stdout.split() if not found.returncode else []
    age = time.time() - max(map(int, stamps)) if stamps else -1
    return age if age >= 0 else None


def _conclusion(old, issue):
    """What an earlier round lends to a reuse: its record if nothing contradicts it, else 'block' or None.

    The record is only as new as the last controller run before the head moved, so a block or malformed report
    posted since, on the main issue or any shard, still counts. A pass has to read back the shards it named: one
    that was deleted or no longer verifies leaves nothing to rest it on, and the round is not reused.
    """
    comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
    parts = shard_parts(old, issue)
    latest = role_reports(old, issue, comments)
    if parts is not None:
        latest.pop(GLM, None)
    if shards_blocked(parts or ()) or any(value in ('block', 'malformed') for value in latest.values()):
        return 'block', None
    record = _record(old, comments) or {}
    shards = None if parts is None else _shard_numbers(parts)
    if record.get('verdict') == 'pass' and record.get('glm_shards') != shards:
        return None, None
    return record.get('verdict'), shards


def reusable(request, pull, late=False):
    """Return (old request, issue, patch id, GLM shards) of an earlier passing round to reuse, WAITING or None.

    Only a patch that a passing round already covers waits for CI, up to CI_GRACE_SECONDS from the later of the base
    and head commits; `late` means ci_hold has already given up on it. Every other case is a full review, at once.
    """
    platform, number = request['platform'], request['number']
    github = platform == 'github'
    rounds = []
    for found in _noticed(request):
        issue = _issue(found, missing=True)
        old = request_from(issue) if issue else None
        if isinstance(old, dict) and old.get('platform') == platform and old.get('number') == number:
            if old == request:
                return None
            if not reused_from(old, issue):
                rounds.append((old, issue))
    label = f'{platform} PR #{number}'
    if rounds and not _fetch_rounds(request, rounds):
        print(f'{label}: could not fetch the commits a reuse compares; full review')
        return None
    current = patch_id(request['base'], request['head']) if rounds else None
    chosen = None
    for old, issue in rounds:
        if not current or patch_id(old['base'], old['head']) != current:
            continue
        verdict, shards = _conclusion(old, issue)
        if verdict == 'block':
            return None
        if verdict == 'pass' and git('merge-base', '--is-ancestor', old['base'], request['base'],
                                     check=False).returncode == 0:
            chosen = (old, issue, current, shards)
    if not chosen:
        return None
    source = chosen[1]['number']
    ci = _github_ci(request['head']) if github else _fresh_ci(pull, chosen[1].get('created_at') or '~')
    if ci == 'success':
        return chosen
    if ci == 'failure':
        print(f'{label}: same patch as review #{source} but CI failed; full review')
        return None
    age = None if late else _scope_age(request)
    if age is None or age >= CI_GRACE_SECONDS:
        print(f'{label}: same patch as review #{source} but CI unsettled past the wait limit; full review')
        return None
    print(f'{label}: same patch as review #{source}; waiting for CI')
    return WAITING


def carry_over(request, pull, late=False):
    """Open a review Issue that reuses an earlier passing round instead of summoning reviewers, or pass on WAITING."""
    found = reusable(request, pull, late)
    if not found or found is WAITING:
        return found
    old, source, digest, shards = found
    platform, number = request['platform'], request['number']
    link = f'https://cnb.cool/{POLICY["cnb"]}/-/issues/{source["number"]}'
    payload = {'request': identity(request), 'source': identity(old), 'source_issue': str(source['number']),
               'source_base': old['base'], 'source_head': old['head'], 'patch_id': digest, 'source_patch_id': digest}
    if shards is not None:
        payload['source_glm_shards'] = shards
    url = (f'https://github.com/{POLICY["github"]}/pull/{number}' if platform == 'github'
           else f'https://cnb.cool/{POLICY["cnb"]}/-/pulls/{number}')
    body = (f'PR 自动结对审核（沿用）：{url}\n\n'
            f'<!-- flclash-pr-review {json.dumps(sign(request))} -->\n'
            f'<!-- flclash-review-reuse {json.dumps(sign(payload))} -->\n\n'
            f'base 快进到 `{request["base"]}`，head `{request["head"]}` 的补丁 patch-id `{digest}` '
            f'与 {link}（base `{old["base"]}`，head `{old["head"]}`，patch-id `{digest}`）相同，'
            '那一轮两位审核者都已通过'
            + (f'（GLM 由分片 {"、".join(f"#{n}" for n in shards)} 通过）' if shards else '')
            + '，本轮沿用其结论，不再召唤审核者，也不开分片。'
            + ('head 上除本门禁外的检查已全部通过。' if platform == 'github'
               else '新 base 上的 pull_request 流水线已全部重跑通过。'))
    issue = _write(f'{CNB}/issues', 'POST', {'title': review_title(request, pull['title']), 'body': body,
                                         'work_mode': False, 'assignees': [POLICY['approver']]})
    _write(f'{GH}/issues/{number}/comments' if platform == 'github' else f'{CNB}/pulls/{number}/comments',
           'POST', {'body': f'结对审核： https://cnb.cool/{POLICY["cnb"]}/-/issues/{issue["number"]}\n'
                         f'base `{request["base"]}` / head `{request["head"]}`，补丁未变，沿用 {link} 的通过结论。'
                         + (f'\n<!-- flclash-review-notice {issue["number"]} -->' if platform == 'cnb' else '')})
    print(f'{platform} PR #{number}: reused review #{source["number"]} (patch-id {digest[:12]})')
    return _issue(issue['number'])


def _reconcile_pull(platform, listed, github_results):
    # Only the list entry carries `created_at` (CNB's detail has no time field), and
    # `ci_hold` needs it while the head has no status yet.
    pull = api(f'{endpoint(platform)}/pulls/{listed["number"]}')
    if listed.get('created_at') and not pull.get('created_at'):
        pull['created_at'] = listed['created_at']
    request = scope(platform, pull)
    waiting, late = (False, False) if platform == 'github' else ci_hold(pull)
    if waiting:
        return
    if platform == 'github':
        from security_finish import mirror_attestation, mirror_record
        attestation = mirror_attestation(pull)
        if attestation:
            github_results.setdefault(request['head'], []).append(('success', attestation))
            print(f'GitHub PR #{request["number"]}: verified identical-tree CNB review and CI attestation')
            return
        forwarded = mirror_record(pull)
        if forwarded and 'cnb_number' in forwarded:
            url = f'https://cnb.cool/{POLICY["cnb"]}/-/pulls/{forwarded["cnb_number"]}'
            github_results.setdefault(request['head'], []).append(('pending', url))
            return
    issue = carry_over(request, pull, late)
    if issue is WAITING:
        return
    issue = issue or ensure_request(request, pull['title'],
        (unsettled_brief(pull) if late else '') + requirement_brief(pull))
    withhold(pull)
    comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
    parts = shard_parts(request, issue)
    status = result(request, issue, comments, parts)
    remember(request, issue, comments, status, parts)
    if issue['state'] == 'open':
        reconsider(request, issue, comments)
        for part in parts or ():
            if part[1]['state'] == 'open':
                reconsider(*part)
    if platform == 'github':
        url = f'https://cnb.cool/{POLICY["cnb"]}/-/issues/{issue["number"]}'
        github_results.setdefault(request['head'], []).append((status, url))
    print(f'{platform} PR #{request["number"]}: {status}')


def reconcile():
    with _one_round():
        started = time.monotonic()
        close_finished_reviews()
        # Flushed, since Actions gives a cancelled step only what already left a piped stdout.
        print(f'Closed finished reviews: {time.monotonic() - started:.1f}s', flush=True)
        github_results = {}
        for platform in ('github', 'cnb'):
            for listed in pages(f'{endpoint(platform)}/pulls?state=open',
                                size_key='per_page' if platform == 'github' else 'page_size'):
                started = time.monotonic()
                try:
                    _reconcile_pull(platform, listed, github_results)
                finally:
                    print(f'{platform} PR #{listed["number"]}: {time.monotonic() - started:.1f}s', flush=True)
        for head, results in github_results.items():
            status, url = min(results, key=lambda r: {'failure': 0, 'pending': 1, 'success': 2}[r[0]])
            existing = api(f'{GH}/commits/{head}/status')['statuses']
            current = next((s for s in existing if s['context'] == CONTEXT), None)
            if not current or current['state'] != status or current.get('target_url') != url:
                _write(f'{GH}/statuses/{head}', 'POST', {'state': status, 'context': CONTEXT,
                       'target_url': url, 'description': 'Both independent reviewers must pass this base/head'})


def close_finished_reviews():
    for item in pages(f'{CNB}/issues?state=open'):
        issue = _issue(item['number'])
        request = request_from(issue)
        if not request:
            continue
        platform = request.get('platform')
        number = request.get('number', '')
        if platform not in ('github', 'cnb') or not str(number).isdigit():
            continue
        pull = api(f'{endpoint(platform)}/pulls/{number}')
        # A GLM shard belongs to the same base/head as its full review and is superseded with it.
        superseded = (pull['state'] == 'open' and scope(platform, pull) != unsharded(request))
        if pull['state'] not in ('closed', 'merged') and not superseded:
            continue
        merged = bool(pull.get('merged') or pull.get('is_merged') or pull['state'] == 'merged')
        _write(f'{CNB}/issues/{issue["number"]}', 'PATCH', {
            'state': 'closed', 'state_reason': 'completed' if merged else 'not_planned'})


def require_candidate(head, base):
    pulls = list(pages(f'{GH}/pulls?state=open', size_key='per_page'))
    matches = [p for p in pulls if p['head']['sha'] == head and p['base']['sha'] == base]
    if not matches or any(state(scope('github', p)) != 'success' for p in matches):
        raise ValueError('Paired PR review missing, stale, blocked or incomplete')


if __name__ == '__main__':
    {'reconcile': reconcile}[sys.argv[1]]()
