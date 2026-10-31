import re

from control import GH, OWNER, api, bot_issues, dispatch


def can_reuse(steps, has_artifact):
    """A built APK survives a later signing or publishing failure; a failed test or source check never reuses it."""
    failed = [s['name'] for s in steps if s.get('conclusion') == 'failure']
    return has_artifact and not any(
        'test' in s.lower() or 'analyz' in s.lower() or 'source' in s.lower() for s in failed)


def notify_once(run, reason):
    title = f'[构建待处理] GitHub #{run["id"]}'
    if any(i['title'] == title for i in bot_issues('all')):
        return
    api(f'{GH}/issues', 'POST', {'title': title, 'assignees': [OWNER], 'body': f'{reason}\n\n{run["html_url"]}'})


def schedule():
    runs = api(f'{GH}/actions/workflows/build.yaml/runs?per_page=30')['workflow_runs']
    for run in runs:
        sha_match = re.fullmatch(r'Android ([0-9a-f]{40})(?: recovery)?', run['display_title'])
        if not sha_match:
            continue
        # A later green build of main replaced this one: nothing is left to reuse or to look at.
        if any(r['id'] > run['id'] and r['conclusion'] == 'success' for r in runs):
            continue
        if run['display_title'].endswith(' recovery'):
            if run['status'] == 'completed' and run['conclusion'] in ('failure', 'timed_out', 'startup_failure'):
                notify_once(run, '产物复用流程失败，已停止自动重试，请检查日志。')
            continue
        sha = sha_match[1]
        if run['status'] != 'completed' or run['conclusion'] in ('success', 'cancelled'):
            continue
        if any(r['id'] > run['id'] and sha in r['display_title'] for r in runs):
            continue
        lock = f'automation/recovery-{run["id"]}'
        if api(f'{GH}/git/ref/heads/{lock}', missing=True):
            continue
        artifacts = api(f'{GH}/actions/runs/{run["id"]}/artifacts')['artifacts']
        has_artifact = any(a['name'] == 'FlClash-arm64-log-history' and not a['expired'] for a in artifacts)
        jobs = api(f'{GH}/actions/runs/{run["id"]}/jobs')['jobs']
        steps = [step for job in jobs for step in job.get('steps', [])]
        if not can_reuse(steps, has_artifact):
            if run['conclusion'] == 'failure':
                notify_once(run, '代码/测试或未分类故障，已暂停自动跟进。需要检查并通过 PR 修复。')
            continue
        if any(r['status'] != 'completed' and sha in r['display_title'] for r in runs):
            continue
        api(f'{GH}/git/refs', 'POST', {'ref': 'refs/heads/' + lock, 'sha': sha})
        try:
            dispatch(sha, run['id'])
        except Exception:
            api(f'{GH}/git/refs/heads/{lock}', 'DELETE')
            raise
        print(f'reuse dispatched for stopped run {run["id"]}')
        return


if __name__ == '__main__':
    schedule()
