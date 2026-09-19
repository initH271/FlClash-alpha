import time
import os
from control import CNB, api, all_issues, pages, comment, parse_request, git
from fallback import remaining_hours

api(f'{CNB}/releases/latest')
print(f'CNB free build budget remaining: {remaining_hours():.2f} core-hours')
for issue in all_issues():
    if issue['state'] != 'open' or not issue['title'].startswith('[上游升级] '):
        continue
    detail = api(f'{CNB}/issues/{issue["number"]}')
    if not parse_request(detail['body']):
        continue
    marker = '<!-- flclash-automation-ready -->'
    if not any(marker in c['body'] for c in pages(f'{CNB}/issues/{issue["number"]}/comments')):
        comment(issue['number'], '自动化连接已配置：每 6 小时发现正式上游版本，每 15 分钟处理批准。'
                '如决定跟进，请在本 Issue 回复单独的 OK；当前仍未批准升级。\n\n' + marker)
    break
started = api(f'{CNB}/build/start', 'POST', {'branch': os.getenv('GITHUB_REF_NAME', 'main'), 'sha': git('rev-parse', 'HEAD'), 'event': 'api_trigger',
              'sync': 'false', 'title': 'Verify automatic release mirror connection'})
for attempt in range(40):
    status = api(f'{CNB}/build/status/{started["sn"]}')['status']
    if status == 'success':
        break
    if status in ('error', 'cancel', 'failed'):
        raise RuntimeError(f'Mirror failed; inspect CNB build {started["sn"]}')
    time.sleep(3)
else:
    raise TimeoutError(f'Mirror still pending; inspect CNB build {started["sn"]}')
print('CNB Issue/comments, releases, quota and build trigger/status permissions verified')
