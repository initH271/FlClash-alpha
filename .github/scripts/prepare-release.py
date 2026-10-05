import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--base')
parser.add_argument('--source', default='HEAD')
parser.add_argument('--dry-run', action='store_true')
args = parser.parse_args()
if not args.dry_run and (args.base is not None or args.source != 'HEAD'):
    parser.error('--base and --source are only allowed with --dry-run')

root = pathlib.Path(__file__).resolve().parents[2]
metadata = json.loads((root / '.github/release.json').read_text(encoding='utf-8'))
command = [
    os.environ.get('DART', 'dart'), str(root / 'tool/release_notes.dart'),
    '--repo', str(root), '--version', metadata['version'],
    '--build', str(metadata['build']), '--source', args.source,
]
if args.base is not None:
    command.extend(['--base', args.base])
generated = json.loads(subprocess.check_output(command, cwd=root, text=True))
if args.dry_run:
    sys.stdout.write(generated['notes'])
    raise SystemExit(0)

source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
if generated['notesSourceSha'] != source:
    raise RuntimeError('Source changed during release preparation')
dist = root / 'dist'
apk = dist / metadata['apk']
metadata['sha256'] = hashlib.sha256(apk.read_bytes()).hexdigest()
metadata['tag'] = f"alpha-{metadata['version']}-{metadata['build']}"
metadata['sourceSha'] = source
metadata.update(generated)
notes = generated['notes']
(dist / 'update.json').write_text(json.dumps(metadata, indent=2) + '\n')
(dist / 'SHA256SUMS.txt').write_text(f"{metadata['sha256']}  {metadata['apk']}\n")
(dist / 'release-notes.md').write_text(
    notes + '\n<!-- flclash-update ' + json.dumps(metadata) + ' -->\n',
    encoding='utf-8',
)
print(metadata['tag'])
