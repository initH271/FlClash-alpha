import json
import os
import re
import urllib.error
import urllib.request

from control import CNB, GH, POLICY, api, approved, comment as post_comment, pages
from reviews import ROLES


def should_wake(issue, comment):
    if issue.get('state') != 'open':
        return False
    body = comment.get('body', '').strip()
    author = comment.get('author') or {}
    if str(issue.get('title', '')).startswith('[需求]'):
        if '<!-- flclash-requirement-wake -->' in body:
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
                post_comment(os.environ['CNB_ISSUE_IID'], '<!-- flclash-requirement-wake -->')
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


if __name__ == '__main__':
    wake()
