#!/usr/bin/env python3
"""Run a CNB NPC for one GitHub PR (review) or one upstream Issue (analysis) and keep its result in a single comment.

Advisory only: every failure ends in "no review this time" and exit 0, so it can never turn a PR red.
The NPC output is untrusted text. It only ever becomes the body of one JSON request, never a command.
"""
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

CNB_API = 'https://api.cnb.cool/507space/FlClash-alpha/-'
EVENT = 'api_trigger_npc_review'
UPSTREAM_EVENT = 'api_trigger_npc_upstream'
OUTPUT_STAGE = 'Review output'
BEGIN, END = 'NPC_REVIEW_BEGIN', 'NPC_REVIEW_END'
MARKER = '<!-- flclash-npc-review -->'
UPSTREAM_MARKER = '<!-- flclash-npc-upstream -->'
BOT = 'github-actions[bot]'
NO_REVIEW = '本次没有审核意见。'
MAX_REVIEW_CHARS = 12000
POLL_SECONDS = 15
# About 10x the measured 56-61 s for PRs of 370-1100 changed lines; maxTurns: 40 bounds the NPC on the CNB side.
DEADLINE_SECONDS = 10 * 60
FINISHED = {'success', 'error', 'failure', 'failed', 'cancel', 'canceled', 'cancelled'}
SHA = re.compile(r'[0-9a-f]{40}')
TAG = re.compile(r'v\d+\.\d+\.\d+')
ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\[\d+m')


def neutralize(text):
    """Strip what could reach a person or spoof the marker from NPC output; keep the text readable."""
    text = re.sub(r'&(?=#?\w+;)', '&amp;', text)
    text = re.sub(r'([@#])(?=[\w-])', '\\1\u200b', text)
    # A plain link to an issue or PR also shows up on that issue's timeline, in other repositories too.
    text = re.sub(r'(github\.com/[\w.-]+/[\w.-]+/(?:issues|pull|discussions))/', '\\1\u200b/', text)
    return text.replace('<!--', '&lt;!--')


def truncate(text, limit=MAX_REVIEW_CHARS):
    return text if len(text) <= limit else text[:limit].rstrip() + '\n\n（输出过长，已截断）'


def render(report, head):
    """The whole comment body. Only `report` comes from the NPC; head was validated before the build started."""
    title = f'{MARKER}\n**NPC 审核** `{head[:12]}`（模型意见，可能有误，以复现为准；不挡合并）\n\n'
    return title + (truncate(neutralize(report.strip())) if report and report.strip() else NO_REVIEW)


def render_upstream(report, tag):
    """Same rule as render: only `report` comes from the NPC, and tag was validated before the build started."""
    title = f'{UPSTREAM_MARKER}\n**NPC 上游分析** `{tag}`（模型意见，可能有误；批准只认 owner 回复 OK）\n\n'
    return title + (truncate(neutralize(report.strip())) if report and report.strip() else NO_REVIEW)


def output_stage(status, name=OUTPUT_STAGE):
    """Find the (pipeline id, stage id) of a stage by name, or None; other stages may run after it."""
    for pipeline_id, pipeline in (status.get('pipelinesStatus') or {}).items():
        for stage in pipeline.get('stages') or []:
            if stage.get('name') == name and stage.get('status') == 'success':
                return pipeline.get('id') or pipeline_id, stage['id']
    return None


def extract_report(content):
    """Cut the report out of a stage log. The last END wins, so NPC text cannot end its own report early."""
    lines = [ANSI.sub('', str(line)).rstrip('\r') for line in content or []]
    ends = [i for i, line in enumerate(lines) if line == END]
    if not ends:
        return ''
    begins = [i for i, line in enumerate(lines[:ends[-1]]) if line == BEGIN]
    return '\n'.join(lines[begins[0] + 1:ends[-1]]).strip() if begins else ''


def existing_comment(comments, marker=MARKER):
    """Pick our comment: the bot's own and carrying the marker, since anyone can paste the marker."""
    return next((c for c in comments if (c.get('user') or {}).get('login') == BOT
                 and (c.get('body') or '').startswith(marker)), None)


def comment_action(comment, report):
    """A new head updates the one comment, so stale advice goes away; no review and no comment writes nothing."""
    if comment:
        return 'PATCH'
    return 'POST' if report and report.strip() else None


def request(url, token, method='GET', data=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'FlClash-alpha-npc-review',
               'Authorization': 'Bearer ' + token}
    if data is not None:
        data = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method),
                                timeout=60) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def cnb(path, method='GET', data=None):
    return request(CNB_API + path, os.environ['CNB_AUTOMATION_TOKEN'], method, data)


def github(path, method='GET', data=None):
    return request(f'https://api.github.com/repos/{os.environ["GITHUB_REPOSITORY"]}{path}',
                   os.environ['GH_TOKEN'], method, data)


def sn_file():
    return pathlib.Path(os.environ.get('RUNNER_TEMP', '/tmp')) / 'npc-review-sn'


def stop(sn):
    try:
        cnb(f'/build/stop/{sn}', 'POST')
    except (OSError, ValueError) as error:
        print(f'::warning::could not stop CNB build {sn}: {type(error).__name__}')


def start_build(event, title, env):
    """`npc` makes it count as dev quota. The env holds only validated values: `$` in it would get expanded."""
    started = cnb('/build/start', 'POST', {'branch': 'main', 'event': event, 'sync': 'false', 'title': title,
                                           'npc': {'name': 'CodeBuddy'}, 'env': env})
    return started['sn']


def wait_for(sn, clock=time.monotonic, sleep=time.sleep, deadline=DEADLINE_SECONDS):
    """Poll until the build ends; past the deadline stop it and return None."""
    begin = clock()
    while clock() - begin < deadline:
        sleep(POLL_SECONDS)
        try:
            status = cnb(f'/build/status/{sn}')
        except (OSError, ValueError):
            continue
        if status.get('status') in FINISHED:
            return status
    stop(sn)
    return None


def fetch_report(sn, status):
    found = output_stage(status)
    if not found:
        return ''
    return extract_report(cnb(f'/build/logs/stage/{sn}/{found[0]}/{found[1]}').get('content'))


def publish(number, body, report, marker=MARKER):
    comments, page = [], 1
    while True:
        batch = github(f'/issues/{number}/comments?per_page=100&page={page}')
        comments += batch
        if len(batch) < 100:
            break
        page += 1
    comment = existing_comment(comments, marker)
    method = comment_action(comment, report)
    body = {'body': body}
    if method == 'PATCH':
        github(f'/issues/comments/{comment["id"]}', 'PATCH', body)
    elif method == 'POST':
        github(f'/issues/{number}/comments', 'POST', body)


def collect(event, title, env):
    """Start the build and return its report; any failure on the way is just an empty report."""
    try:
        if not os.environ.get('CNB_AUTOMATION_TOKEN'):
            raise ValueError('CNB_AUTOMATION_TOKEN is not available')
        sn = start_build(event, title, env)
        sn_file().write_text(sn)
        print(f'CNB build: https://cnb.cool/507space/FlClash-alpha/-/build/logs/{sn}')
        status = wait_for(sn)
        if status is not None:
            return fetch_report(sn, status)
    except (OSError, ValueError, KeyError) as error:
        # The exception text can carry a server body; the type is enough to look further.
        print(f'::warning::no NPC report: {type(error).__name__}')
    return ''


def run():
    number, base, head = (os.environ[name] for name in ('PR_NUMBER', 'PR_BASE', 'PR_HEAD'))
    if not (number.isdigit() and SHA.fullmatch(base) and SHA.fullmatch(head)):
        raise ValueError('unexpected PR number or SHA')
    report = collect(EVENT, f'NPC review GitHub PR {number}', {'PR_NUMBER': number, 'PR_BASE': base, 'PR_HEAD': head})
    publish(number, render(report, head), report)


def run_upstream():
    number, tag, base, head = (os.environ[name] for name in ('ISSUE_NUMBER', 'UPSTREAM_TAG', 'UPSTREAM_BASE', 'UPSTREAM_HEAD'))
    if not (number.isdigit() and TAG.fullmatch(tag) and SHA.fullmatch(base) and SHA.fullmatch(head)):
        raise ValueError('unexpected Issue number, tag or SHA')
    report = collect(UPSTREAM_EVENT, f'NPC analysis of upstream {tag}',
                     {'ISSUE_NUMBER': number, 'UPSTREAM_TAG': tag, 'UPSTREAM_BASE': base, 'UPSTREAM_HEAD': head})
    publish(number, render_upstream(report, tag), report, UPSTREAM_MARKER)


def main(argv):
    try:
        if argv[1:] == ['stop']:
            if sn_file().exists():
                stop(sn_file().read_text().strip())
        elif argv[1:] == ['upstream']:
            run_upstream()
        else:
            run()
    except Exception as error:  # noqa: BLE001 - advisory step: nothing here may fail the PR.
        print(f'::warning::NPC step ended early: {type(error).__name__}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
