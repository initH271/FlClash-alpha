import os
import re
from control import CNB, api, git

tag = os.environ['PROBE_TAG']
if not re.fullmatch(r'automation-permission-\d+', tag):
    raise ValueError('Unexpected temporary probe tag')
if api(f'{CNB}/git/tags/{tag}', missing=True) is not None:
    raise ValueError('Probe tag already exists; refusing to touch it')
release = api(f'{CNB}/releases', 'POST', {'tag_name': tag,
    'target_commitish': git('rev-parse', 'HEAD'), 'draft': True,
    'name': 'Temporary automation permission check', 'body': 'Temporary credential validation; never published.'})
try:
    if not release['draft']:
        raise ValueError('Permission probe must stay draft')
    print('Temporary Release write permission verified')
finally:
    api(f'{CNB}/releases/{release["id"]}', 'DELETE')
    api(f'{CNB}/git/tags/{tag}', 'DELETE', missing=True)
