import hashlib
import json
import shutil
from control import ROOT, git

proof = json.loads((ROOT / 'reused/update.json').read_text())
expected = json.loads((ROOT / '.github/release.json').read_text())
apk = ROOT / 'reused' / expected['apk']
if proof.get('sourceSha') != git('rev-parse', 'HEAD') or proof['build'] != expected['build']:
    raise ValueError('Reusable artifact does not match source/version')
if hashlib.sha256(apk.read_bytes()).hexdigest() != proof['sha256']:
    raise ValueError('Reusable artifact hash mismatch')
destination = ROOT / 'build/app/outputs/flutter-apk/app-release.apk'
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(apk, destination)
