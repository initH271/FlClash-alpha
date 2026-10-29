import datetime
import json
import re

from control import CNB, GH, POLICY, api, comment, pages

WORDS = ('HOLD', 'RELEASE')
UPSTREAM_PREFIX = 'automation/upstream-'
APPROVED_BUILD = 'FlClash/approved-build'
RUNS_URL = GH + '/actions/workflows/build.yaml/runs'
LOCK_LIMIT_MINUTES = 180
REMIND_AFTER_MINUTES = 90
EXPIRED_MARKER = '<!-- flclash-release-lock-expired {} -->'
REMIND_MARKER = '<!-- flclash-release-lock-remind {} -->'
REQUIREMENT_DEFERRED = '<!-- flclash-requirement-deferred {} -->'

_release = None


def command(item):
    """Return the HOLD or RELEASE the owner wrote as the whole comment, else ''."""
    author = item.get('author') or {}
    if author.get('username') != POLICY['approver'] or author.get('is_npc') is not False:
        return ''
    body = (item.get('body') or '').strip()
    return body if body in WORDS else ''


def held(comments):
    """Return when the owner last took the branch, or '' while it is not taken."""
    owner = [item for item in comments or []
             if command(item) and (item.get('author') or {}).get('username') == POLICY['approver']]
    owner.sort(key=lambda item: item.get('created_at') or '')
    return owner[-1].get('created_at', '') if owner and command(owner[-1]) == 'HOLD' else ''


def _clock():
    """Wall clock the lock measures against; tests replace it to fix the time."""
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(value, now=None):
    text = (value or '').replace('Z', '+00:00')
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return now
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def minutes_between(since, now):
    if not since or now is None:
        return 0
    return max(0, int((now - stamp(since, now)).total_seconds() // 60))


def issue_number(body):
    match = re.search(r'CNB Issue #(\d+)', body or '')
    return match.group(1) if match else ''


def candidates():
    """Return the open GitHub pull requests a running release would invalidate."""
    for pull in pages(f'{GH}/pulls?state=open', size_key='per_page'):
        head = pull.get('head') or {}
        base = pull.get('base') or {}
        if (not (head.get('ref') or '').startswith(UPSTREAM_PREFIX) or base.get('ref') != 'main'
                or (head.get('repo') or {}).get('full_name') != POLICY['github']):
            continue
        yield {'head': head.get('sha') or '', 'ref': head.get('ref') or '', 'pull': pull.get('number'),
               'issue': issue_number(pull.get('body'))}


def running_lock(found):
    """Return the oldest unfinished build.yaml run for a candidate sha, or None."""
    runs = api(RUNS_URL + '?per_page=100').get('workflow_runs') or []
    open_runs = [run for run in running_owner(found, runs) if run.get('status') != 'completed']
    if not open_runs:
        return None
    return min(open_runs, key=lambda run: run.get('created_at') or '')


def running_owner(found, runs):
    # build.yaml names a run `Android <sha>`, so a candidate matches on its commit.
    shas = [item['head'] for item in found if item['head']]
    return [run for run in runs
            if any(sha in (run.get('display_title') or '') for sha in shas)]


def pending_status(item):
    status = api(f'{GH}/commits/{item["head"]}/status') if item['head'] else {}
    for row in (status or {}).get('statuses') or []:
        if row.get('context') == APPROVED_BUILD and row.get('state') == 'pending':
            return row
    return None


def expired_notice(item, notify):
    """Release a pending status past the limit, once per sha and only when asked to."""
    if not notify or EXPIRED_MARKER.format(item['head']) in said(read_comments(item['issue'])):
        return
    approver = '@' + POLICY['approver']
    comment(item['issue'], EXPIRED_MARKER.format(item['head']) + '\n\n'
            + f'{approver}，候选 `{item["head"][:12]}`（GitHub PR #{item["pull"]}）的 approved-build 状态已 pending '
            f'超过 {LOCK_LIMIT_MINUTES} 分钟，该候选不再算作发版锁；'
            '如果没有其他发版在进行，下一轮起恢复合并。'
            '构建确实还在跑时，请手动冻结（CNB PR 标题加 `WIP: `，GitHub PR 转为草稿）。')


def remind(lock, notify):
    if not (notify and REMIND_MARKER.format(lock['head']) not in said(read_comments(lock['issue']))):
        return
    approver = '@' + POLICY['approver']
    comment(lock['issue'], REMIND_MARKER.format(lock['head']) + '\n\n'
            + f'{approver}，发版锁已持续约 {lock["minutes"]} 分钟，候选 `{lock["head"][:12]}`'
            f'（GitHub PR #{lock["pull"]}）的发版还没结束（依据：{lock["evidence"]}）。'
            '锁内控制器不把任何 PR 合入 main。构建卡住时，取消该 build.yaml 运行，'
            f'或者把该提交的 `{APPROVED_BUILD}` 状态改成 failure，下一轮就会解锁。')


def report(lock, notify):
    """Tell the owner once a release has outlasted the reminder threshold."""
    if lock['minutes'] <= REMIND_AFTER_MINUTES or not notify:
        return
    if lock['issue']:
        remind(lock, notify)
    else:
        print(f'release lock on {lock["head"][:12]} has run {lock["minutes"]} minutes '
              'but the pull request names no CNB issue')


def release_lock(now=None, notify=True):
    """Return the release in flight that keeps GitHub main frozen, or None.

    The answer is cached for the whole process: one controller pass must see one release.
    None means nobody asked GitHub yet, False means no lock, a dict is the lock.
    """
    global _release
    if now is None:
        now = _clock()
    if _release is None:
        _release = measure(now, notify) or False
    return dict(_release) if _release else None


def measure(now, notify):
    found = list(candidates())
    if not found:
        return None
    run = running_lock(found)
    if run:
        title = run.get('display_title') or ''
        owner = next(item for item in found if item['head'] and item['head'] in title)
        lock = dict(owner, since=run.get('created_at') or '', evidence='build.yaml 运行未结束')
    else:
        locks = []
        for item in found:
            row = pending_status(item)
            if not row:
                continue
            # Every candidate is checked: an expired one drops out alone, the others still count.
            since = row.get('created_at') or ''
            if minutes_between(since, now) > LOCK_LIMIT_MINUTES:
                if item['issue']:
                    expired_notice(item, notify)
                else:
                    print(f'release lock expired on {item["head"][:12]} '
                          'but the pull request names no CNB issue')
                continue
            locks.append(dict(item, since=since, evidence='approved-build 状态 pending'))
        if not locks:
            return None
        lock = min(locks, key=lambda item: stamp(item['since'], now))
    lock = dict(lock, source='release', minutes=minutes_between(lock['since'], now))
    report(lock, notify)
    return lock


def read_comments(number):
    return list(pages(f'{CNB}/issues/{number}/comments'))


def said(comments):
    return ' '.join(item.get('body') or '' for item in comments)


def deferred(number, head, pull):
    """Tell a requirement once that the release in flight is why it waits."""
    marker = REQUIREMENT_DEFERRED.format(head)
    if marker in said(read_comments(number)):
        return
    comment(number, marker + '\n\n'
            + f'发版进行中（候选 `{head[:12]}`，GitHub PR #{pull}）：控制器暂缓把本需求的 GitHub PR 合入 main；'
            '转发、同步 main 和审核照常进行，发版结束后控制器下一轮运行时自动合并。')


def paused(scope, branch='', comments=None, now=None):
    """Return what pauses an action, or None.

    'branch' covers the actions that only write the requirement branch; 'main' covers
    the ones that join main or refresh a branch waiting to merge. The owner's HOLD comes
    first, then a release in flight freezes main while leaving forwarding and syncing alone.
    """
    if scope not in ('branch', 'main'):
        raise ValueError('scope must be branch or main')
    branch = branch or ''
    if branch.startswith('automation/req-') and comments is None:
        number = branch.removeprefix('automation/req-').split('/')[0]
        if number.isdigit():
            comments = list(pages(f'{CNB}/issues/{number}/comments'))
    since = held(comments or [])
    if since and branch.startswith('automation/req-'):
        return {'source': 'hold', 'head': '', 'ref': branch, 'branch': branch, 'since': since}
    return release_lock(now) if scope == 'main' else None


def status(branch=''):
    """Read-only view of what would pause an action right now."""
    lock = release_lock(notify=False)
    hold = ''
    number = branch.removeprefix('automation/req-').split('/')[0]
    if number.isdigit():
        try:
            seen = read_comments(number)
        except (RuntimeError, IndexError, ValueError):
            seen = []
        hold = held(seen)
    print(json.dumps({'release': lock, 'hold': hold or None}, ensure_ascii=False))


if __name__ == '__main__':
    import sys
    if sys.argv[1:2] == ['status']:
        status(*sys.argv[2:3])
    else:
        raise SystemExit('usage: pause.py status [automation/req-<n>]')
