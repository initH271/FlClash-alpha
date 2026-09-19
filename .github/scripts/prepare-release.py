import hashlib
import json
import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[2]
metadata = json.loads((root / '.github/release.json').read_text(encoding='utf-8'))
dist = root / 'dist'
apk = dist / metadata['apk']
metadata['sha256'] = hashlib.sha256(apk.read_bytes()).hexdigest()
metadata['tag'] = f"alpha-{metadata['version']}-{metadata['build']}"
metadata['sourceSha'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
notes = (root / '.github/release-notes.md').read_text(encoding='utf-8')
metadata['notes'] = notes
(dist / 'update.json').write_text(json.dumps(metadata, indent=2) + '\n')
(dist / 'SHA256SUMS.txt').write_text(f"{metadata['sha256']}  {metadata['apk']}\n")
(dist / 'release-notes.md').write_text(
    notes + '\n<!-- flclash-update ' + json.dumps(metadata) + ' -->\n',
    encoding='utf-8',
)
print(metadata['tag'])
