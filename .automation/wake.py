import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from control import CNB, GH, POLICY, api, approved, check_name, comment as post_comment, gating_statuses, pages
from reviews import ROLES, scope

SETTLED = {'success', 'error', 'failure', 'cancel', 'cancelled'}
EXPECTED = {'Paired review gate', 'Dependency vulnerability gate'}
WAKE_MARKER = '<!-- flclash-requirement-wake'
HALTED = {'stuck', 'quota', 'invalid'}
STALL_SECONDS = 35 * 60
OPEN_GRACE_SECONDS = 10 * 60
IDLE_SECONDS = 40 * 60
MERGE_RETRY_SECONDS = 30 * 60
MERGE_RETRIES = 3


def should_wake(issue, comment):
    if issue.get('state') != 'open':
        return False
    body = comment.get('body', '').strip()
    author = comment.get('author') or {}
    if str(issue.get('title', '')).startswith('[需求]'):
        if WAKE_MARKER in body:
            return True
        return (author.get('is_npc') is True and author.get('username') in (
            f'{POLICY["cnb"]}(开发助手)', f'{POLICY["cnb"]}(审查助手)'))
    if '<!-- flclash-security-group ' in issue.get('body', ''):
        return (author.get('is_npc') is True
                and author.get('username') == f'{POLICY["cnb"]}(开发助手)')
    if '<!-- flclash-upstream ' in issue.get('body', ''):
        match = re.search(r'"tag"\s*:\s*"(v[0-9]+\.[0-9]+\.[0-9]+)"', issue['body'])
        return bool(match and approved(comment, match[1]))
    return ('<!-- flclash-pr-review ' in issue.get('body', '')
            and author.get('is_npc') is True
            and author.get('username') in [f'{POLICY["cnb"]}({r})' for r in ROLES]
            and re.search(r'^FLCLASH_REVIEW \{', body, re.M) is not None)


def dispatch():
    token = os.environ.get('CNB_GITHUB_DISPATCH_TOKEN')
    if not token or token.startswith('REPLACE_'):
        raise RuntimeError('Configure CNB_GITHUB_DISPATCH_TOKEN in the dedicated CNB KeyStore')
    request = urllib.request.Request(f'{GH}/actions/workflows/upstream.yaml/dispatches',
        data=json.dumps({'ref': 'main', 'inputs': {'operation': 'all'}}).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                 'Accept': 'application/vnd.github+json', 'User-Agent': 'FlClash-event-bridge'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30):
            pass
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'GitHub workflow dispatch failed: HTTP {error.code}') from None
    print('Requested controller reconciliation')


def wake():
    event = os.environ.get('CNB_EVENT', '')
    if event in ('crontab: */15 * * * *', 'pull_request.target'):
        dispatch()
        return
    if event == 'issue' or (event.startswith('issue.') and not event.startswith('issue.comment')):
        opened = api(f'{CNB}/issues/{os.environ["CNB_ISSUE_IID"]}')
        author = opened.get('author') or {}
        if (str(opened.get('title', '')).startswith('[需求]') and author.get('username') == POLICY['approver']
                and author.get('is_npc') is False):
            if not os.environ.get('CNB_GITHUB_DISPATCH_TOKEN'):
                post_comment(os.environ['CNB_ISSUE_IID'], WAKE_MARKER + ' -->')
                print('Requested comment bridge')
                return
            dispatch()
            return
        print('Issue does not require controller work')
        return
    number = os.environ['CNB_ISSUE_IID']
    issue = api(f'{CNB}/issues/{number}')
    comments = list(pages(f'{CNB}/issues/{number}/comments'))
    if not comments:
        return
    latest = max(comments, key=lambda c: (c['created_at'], int(c['id'])))
    if not should_wake(issue, latest):
        print('Comment does not require controller work')
        return
    dispatch()


def wake_when_green(attempts=100, pause=30):
    number = os.environ['CNB_PULL_REQUEST_IID']
    head = os.environ['CNB_PULL_REQUEST_SHA']
    for _ in range(attempts):
        pull = api(f'{CNB}/pulls/{number}')
        if pull.get('state') != 'open' or scope('cnb', pull)['head'] != head:
            print('PR moved; the newer event owns the wake')
            return
        statuses = gating_statuses(api(f'{CNB}/pulls/{number}/commit-statuses'))
        if EXPECTED <= {check_name(item) for item in statuses} and all(
                item['state'] in SETTLED for item in statuses):
            if all(item['state'] == 'success' for item in statuses):
                dispatch()
            else:
                print('Checks failed; the failure path owns the next step')
            return
        time.sleep(pause)
    print('Checks did not settle in time')


def _signed(comments):
    found = []
    for item in comments:
        match = re.search(r'<!-- flclash-requirement (\{[^\r\n]+\}) -->', item.get('body', ''))
        if not match:
            continue
        try:
            found.append((item, json.loads(match[1])['payload']))
        except (ValueError, KeyError, TypeError):
            continue
    return found


def _age(stamp, now):
    import datetime
    return now - datetime.datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()


def stalled(issue, comments, pull, checks, now):
    """Return a one-time key for a requirement state no event will advance, or ''."""
    key = _stalled(issue, comments, pull, checks, now)
    if key or not pull or not comments or (checks and all(item['state'] == 'success' for item in checks)):
        return key
    if _signed(comments) and _signed(comments)[-1][1].get('phase') in HALTED:
        return ''
    latest = max(item.get('created_at', '') for item in comments)
    return f'idle-{pull["head"]["sha"]}' if latest and _age(latest, now) > IDLE_SECONDS else ''


def _stalled(issue, comments, pull, checks, now):
    signed = _signed(comments)
    if signed and signed[-1][1].get('phase') in HALTED:
        return ''
    if not signed:
        return 'open' if _age(issue['created_at'], now) > OPEN_GRACE_SECONDS else ''
    if any('需求已送至 GitHub' in item.get('body', '') for item in comments):
        earlier = sum(f'{WAKE_MARKER} merge-' in item.get('body', '') for item in comments)
        return f'merge-{int(now // MERGE_RETRY_SECONDS)}' if earlier < MERGE_RETRIES else ''
    if pull and checks and all(item['state'] == 'success' for item in checks):
        return f'green-{pull["head"]["sha"]}'
    marker, payload = signed[-1]
    attempts = [entry for entry in (marker.get('statuses') or {}).get('npc', [])
                if (entry.get('statuses') or [])]
    if not attempts:
        return f'stall-{marker["id"]}' if _age(marker['created_at'], now) > STALL_SECONDS else ''
    last = attempts[-1]['statuses'][-1]
    if last.get('state') not in SETTLED:
        return ''
    role = attempts[-1].get('context', {}).get('npc.name', '')
    reported = any(item.get('created_at', '') > marker['created_at']
                   and (item.get('author') or {}).get('username') == f'{POLICY["cnb"]}({role})'
                   for item in comments)
    return '' if reported else f'silent-{attempts[-1].get("context", {}).get("sn", marker["id"])}'


def watchdog(now=None):
    now = time.time() if now is None else now
    pulls = list(pages(f'{CNB}/pulls?state=open'))
    for summary in pages(f'{CNB}/issues?state=open'):
        author = summary.get('author') or {}
        if (not str(summary.get('title', '')).startswith('[需求]') or author.get('username') != POLICY['approver']
                or author.get('is_npc') is not False):
            continue
        number = str(summary['number'])
        comments = list(pages(f'{CNB}/issues/{number}/comments'))
        pull = next((item for item in pulls
                     if item['head']['ref'].removeprefix('refs/heads/') == f'automation/req-{number}'), None)
        checks = gating_statuses(api(f'{CNB}/pulls/{pull["number"]}/commit-statuses')) if pull else []
        key = stalled(summary, comments, pull, checks, now)
        if key and not any(f'{WAKE_MARKER} {key} -->' in item.get('body', '') for item in comments):
            post_comment(number, f'{WAKE_MARKER} {key} -->')
            print(f'Woke requirement #{number}: {key}')


if __name__ == '__main__':
    commands = {'settled': wake_when_green, 'watchdog': watchdog}
    commands.get(sys.argv[1] if sys.argv[1:] else '', wake)()
