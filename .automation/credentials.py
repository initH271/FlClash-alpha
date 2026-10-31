import os
import time
from control import CNB, api, git

api(f'{CNB}/releases/latest')
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
print('CNB release read and mirror trigger/status permissions verified')
