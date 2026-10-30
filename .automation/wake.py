import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import pause
from control import CNB, GH, POLICY, api, approved, check_name, comment as post_comment, gating_statuses, pages
from reviews import CI_PIPELINES, ROLES, request_from, scope

SETTLED = {'success', 'error', 'failure', 'cancel', 'cancelled'}
WAKE_MARKER = '<!-- flclash-requirement-wake'
ACTIVE = ('<!-- flclash-pr-review ', '<!-- flclash-upstream ', '<!-- flclash-security-group ')
HALTED = {'stuck', 'quota', 'invalid'}
STALL_SECONDS = 35 * 60
OPEN_GRACE_SECONDS = 10 * 60
IDLE_SECONDS = 40 * 60
IDLE_RETRIES = 3
MERGE_RETRY_SECONDS = 30 * 60
MERGE_RETRIES = 3


def should_wake(issue, comment):
    if issue.get('state') != 'open':
        return False
    body = comment.get('body', '').strip()
    author = comment.get('author') or {}
    if str(issue.get('title', '')).startswith('[需求]'):
        if pause.command(comment):
            return True
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
    if event == 'pull_request.target':
        dispatch()
        return
    if event == 'crontab: */15 * * * *':
        if busy():
            dispatch()
        else:
            print('idle')
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


def busy():
    """Return True when an open issue or requirement PR still needs the controller; a HOLD idles its requirement."""
    approved_branch = re.compile(r'(automation/req-|security/group-).+')
    holds = {}

    def held(number):
        if number not in holds:
            holds[number] = bool(pause.held(list(pages(f'{CNB}/issues/{number}/comments'))))
        return holds[number]

    def waiting(pull):
        requirement = re.fullmatch(r'automation/req-(\d+)', pull['head']['ref'].removeprefix('refs/heads/'))
        return bool(requirement) and held(requirement[1])

    pulls = None
    for summary in pages(f'{CNB}/issues?state=open'):
        author = summary.get('author') or {}
        if (str(summary.get('title', '')).startswith('[需求]')
                and author.get('username') == POLICY['approver'] and author.get('is_npc') is False):
            if not held(str(summary['number'])):
                return True
            continue
        body = str(summary.get('body', ''))
        if not any(marker in body for marker in ACTIVE):
            # A list without bodies costs one detail read per issue.
            detail = api(f'{CNB}/issues/{summary["number"]}', missing=True) or {}
            body = str(detail.get('body', ''))
        if not any(marker in body for marker in ACTIVE):
            continue
        # A review of a held requirement's open PR waits with it; any other review still needs the controller.
        request = request_from({**summary, 'body': body}, signed=False) or {}
        if pulls is None:
            pulls = list(pages(f'{CNB}/pulls?state=open'))
        reviewed = next((pull for pull in pulls if request.get('platform') == 'cnb'
                         and str(pull['number']) == str(request.get('number'))), None)
        if reviewed is None or not waiting(reviewed):
            return True
    pulls = list(pages(f'{CNB}/pulls?state=open')) if pulls is None else pulls
    return any(approved_branch.fullmatch(pull['head']['ref'].removeprefix('refs/heads/')) and not waiting(pull)
               for pull in pulls)


def ci_done(own=''):
    """Wake the requirement issue once every other main.pull_request pipeline has finished; never raises."""
    try:
        match = re.fullmatch(r'(automation/req-|refs/heads/automation/req-)(\d+)',
                             os.environ.get('CNB_PULL_REQUEST_BRANCH', ''))
        if not match:
            print('Not a requirement branch; no wake')
            return
        number = match[2]
        sha = os.environ.get('CNB_PULL_REQUEST_SHA', '')
        pull = api(f'{CNB}/pulls/{os.environ["CNB_PULL_REQUEST_IID"]}')
        if pull.get('state') != 'open' or scope('cnb', pull)['head'] != sha:
            print('PR moved; the newer event owns the wake')
            return
        states = {}
        for item in gating_statuses(api(f'{CNB}/pulls/{pull["number"]}/commit-statuses')):
            states.setdefault(check_name(item), []).append(item['state'])
        others = [name for name in CI_PIPELINES if name != own]
        if any(name not in states or any(state not in SETTLED for state in states[name]) for name in others):
            print('Other pipelines are still running')
            return
        marker = f'{WAKE_MARKER} ci-{sha} -->'
        if any(marker in str(item.get('body', '')) for item in pages(f'{CNB}/issues/{number}/comments')):
            print('Wake already posted')
            return
        post_comment(number, marker)
        print(f'Woke requirement #{number} after CI')
    except Exception as error:  # The pipeline must never fail on a wake attempt.
        print(f'Wake skipped: {type(error).__name__}')


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
    if pause.held(comments):
        return ''
    key = _stalled(issue, comments, pull, checks, now)
    if key or not pull or not comments or (checks and all(item['state'] == 'success' for item in checks)):
        return key
    # A stuck requirement may still be resynced or forwarded, so it gets one idle wake per head.
    if _signed(comments) and _signed(comments)[-1][1].get('phase') in HALTED - {'stuck'}:
        return ''
    latest = max(item.get('created_at', '') for item in comments)
    if not latest or _age(latest, now) <= IDLE_SECONDS:
        return ''
    # Each wake marker restarts the idle clock, so retries are spaced out; a silent reviewer failure needs more than one.
    prefix = f'{WAKE_MARKER} idle-{pull["head"]["sha"]}'
    earlier = sum(prefix in item.get('body', '') for item in comments)
    return f'idle-{pull["head"]["sha"]}-{earlier + 1}' if earlier < IDLE_RETRIES else ''


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


def watchdog_with_status():
    watchdog()
    try:
        import status
        status.refresh()
    except Exception as error:  # The status view must never stop the wake bridge.
        # API errors are already redacted by control.api; the cap keeps any other message short.
        print(f'Status issue skipped: {type(error).__name__}: {str(error)[:200]}')


if __name__ == '__main__':
    commands = {'watchdog': watchdog_with_status, 'ci-done': lambda name='': ci_done(name)}
    commands.get(sys.argv[1] if sys.argv[1:] else '', wake)(*sys.argv[2:])
