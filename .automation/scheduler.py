import datetime
import json
import re

from control import GH, CNB, POLICY, api, dispatch, all_issues
from fallback import remaining_hours


def recovery_kind(steps, conclusion, has_artifact, annotations=''):
    failed = [s['name'] for s in steps if s.get('conclusion') == 'failure']
    if any('test' in s.lower() or 'analyz' in s.lower() or 'source' in s.lower() for s in failed):
        return None
    if has_artifact:
        return 'reuse'
    if conclusion == 'startup_failure':
        return 'fallback'
    if re.search(r'no space left on device|runner.*lost communication|runner.*offline', annotations, re.I):
        return 'fallback'
    setup = ('Setup', 'Set up', 'Run actions/', 'Run subosito/', 'Run nttld/',
             'Run gradle/', 'Run Swatinem/', 'Free runner')
    return 'fallback' if failed and all(s.startswith(setup) for s in failed) else None


def notify_once(run, reason):
    title = f'[构建待处理] GitHub #{run["id"]}'
    if any(i['title'] == title for i in all_issues()):
        return
    api(f'{CNB}/issues', 'POST', {'title': title, 'assignees': [POLICY['approver']],
        'body': f'{reason}\n\n{run["html_url"]}\n\n'
        '@507space/FlClash-alpha(审查助手) 请分析失败原因；不要重复编译或直接发布。'})


def schedule():
    runs = api(f'{GH}/actions/workflows/build.yaml/runs?per_page=30')['workflow_runs']
    now = datetime.datetime.now(datetime.timezone.utc)
    for run in runs:
        sha_match = re.fullmatch(r'Android ([0-9a-f]{40})(?: recovery)?', run['display_title'])
        if not sha_match or run['display_title'].endswith(' recovery'):
            continue
        sha = sha_match[1]
        if run['status'] == 'in_progress' or run['conclusion'] == 'success':
            continue
        if any(r['id'] > run['id'] and sha in r['display_title'] for r in runs):
            continue
        lock = f'automation/recovery-{run["id"]}'
        if api(f'{GH}/git/ref/heads/{lock}', missing=True):
            continue
        if run['status'] == 'queued':
            created = datetime.datetime.fromisoformat(run['created_at'].replace('Z', '+00:00'))
            if (now - created).total_seconds() < POLICY['queue_timeout_minutes'] * 60:
                continue
            api(f'{GH}/git/refs', 'POST', {'ref': f'refs/heads/automation/queue-cancel-{run["id"]}', 'sha': sha})
            api(f'{GH}/actions/runs/{run["id"]}/cancel', 'POST')
            print('Requested cancellation; next scheduler pass verifies it stopped')
            return
        if run['status'] != 'completed':
            continue
        artifacts = api(f'{GH}/actions/runs/{run["id"]}/artifacts')['artifacts']
        has_artifact = any(a['name'] == 'FlClash-arm64-log-history' and not a['expired'] for a in artifacts)
        jobs = api(f'{GH}/actions/runs/{run["id"]}/jobs')['jobs']
        steps = [step for job in jobs for step in job.get('steps', [])]
        annotations = ' '.join(a.get('message', '') for job in jobs
                               for a in api(job['check_run_url'] + '/annotations'))
        kind = recovery_kind(steps, run['conclusion'], has_artifact, annotations)
        if run['conclusion'] == 'cancelled' and api(
                f'{GH}/git/ref/heads/automation/queue-cancel-{run["id"]}', missing=True):
            kind = 'fallback'
        elif run['conclusion'] == 'cancelled':
            continue
        if kind is None:
            if run['conclusion'] == 'failure':
                notify_once(run, '代码/测试或未分类故障，已暂停自动跟进。需要检查并通过 PR 修复。')
            continue
        if kind == 'fallback':
            try:
                enough_quota = remaining_hours() >= POLICY['fallback_min_core_hours']
            except RuntimeError:
                notify_once(run, '无法读取 CNB 额度，未自动切换。请检查令牌 group-resource:r 权限。')
                continue
            if not enough_quota:
                notify_once(run, 'CNB 免费额度不足，未执行备用构建。')
                continue
        if any(r['status'] != 'completed' and sha in r['display_title'] for r in runs):
            continue
        api(f'{GH}/git/refs', 'POST', {'ref': 'refs/heads/' + lock, 'sha': sha})
        try:
            dispatch(sha, run['id'] if kind == 'reuse' else '', 'true' if kind == 'fallback' else 'false')
        except Exception:
            api(f'{GH}/git/refs/heads/{lock}', 'DELETE')
            raise
        print(f'{kind} dispatched for stopped run {run["id"]}')
        return


if __name__ == '__main__':
    schedule()
