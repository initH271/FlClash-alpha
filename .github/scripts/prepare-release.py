import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_notes

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    '--base',
    default=None,
    help='Alpha tag to diff against instead of the newest eligible one',
)
parser.add_argument(
    '--dry-run',
    action='store_true',
    help='Print the release notes without writing dist/',
)
args = parser.parse_args()

root = pathlib.Path(__file__).resolve().parents[2]
metadata = json.loads((root / '.github/release.json').read_text(encoding='utf-8'))
dist = root / 'dist'

if args.dry_run:
    print(metadata['tag'] if 'tag' in metadata else
          f"alpha-{metadata['version']}-{metadata['build']}")
    sys.stdout.write(
        release_notes.generate(root, metadata['version'], metadata['build'], args.base)['notes']
    )
    raise SystemExit(0)

apk = dist / metadata['apk']
metadata['sha256'] = hashlib.sha256(apk.read_bytes()).hexdigest()
metadata['tag'] = f"alpha-{metadata['version']}-{metadata['build']}"
metadata['sourceSha'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()

generated = release_notes.generate(root, metadata['version'], metadata['build'], args.base)
notes = generated['notes']

generated = release_notes.generate(root, metadata['version'], metadata['build'])
notes = generated['notes']
metadata['notes'] = notes
metadata['notesBaseTag'] = generated['base_tag']
metadata['notesBaseSha'] = generated['base_sha']
metadata['notesSourceSha'] = generated['source_sha']
(dist / 'update.json').write_text(json.dumps(metadata, indent=2) + '\n')
(dist / 'SHA256SUMS.txt').write_text(f"{metadata['sha256']}  {metadata['apk']}\n")
(dist / 'release-notes.md').write_text(
    notes + '\n<!-- flclash-update ' + json.dumps(metadata) + ' -->\n',
    encoding='utf-8',
)
print(metadata['tag'])
