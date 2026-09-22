import json
import os
from control import GH, ROOT, api, git, validate_source

validate_source()
metadata = json.loads((ROOT / '.github/release.json').read_text())
tag = f"alpha-{metadata['version']}-{metadata['build']}"
release = api(f'{GH}/releases/tags/{tag}', missing=True)
already = release is not None and not release['draft']
if already and release['target_commitish'] != git('rev-parse', 'HEAD'):
    print('Build number already published from another commit; this push will not publish again')
compile_source = not already and not os.getenv('REUSE_RUN') and os.getenv('CNB_FALLBACK') != 'true'
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write(f'compile={str(compile_source).lower()}\nactive={str(not already).lower()}\n')
