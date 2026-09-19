import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import tomllib

from control import api

LOCKS = ('services/helper/Cargo.lock', 'plugins/rust_api/rust/Cargo.lock')


def json_stream(text):
    decoder = json.JSONDecoder()
    while text.strip():
        value, end = decoder.raw_decode(text.lstrip())
        yield value
        text = text.lstrip()[end:]


def inventory(root):
    modules = subprocess.run(['go', 'list', '-mod=readonly', '-m', '-json', 'all'],
        cwd=root / 'core', env=dict(os.environ, GOTOOLCHAIN='local', GOWORK='off'),
        check=True, capture_output=True, text=True, timeout=240).stdout
    packages, unscanned = [], []
    for module in json_stream(modules):
        if module.get('Main'):
            continue
        effective = module.get('Replace', module)
        item = {'file': 'core/go.mod', 'name': module['Path'], 'ecosystem': 'Go'}
        if not effective.get('Version'):
            unscanned.append(item)
            continue
        if effective['Path'] != module['Path']:
            unscanned.append(item)
        packages.append(dict(item, name=effective['Path'], version=effective['Version']))
    for filename in LOCKS:
        path = root / filename
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Dependency file escapes repository')
        for package in tomllib.loads(path.read_text())['package']:
            source = package.get('source', '')
            if not source:
                continue
            item = {'file': filename, 'name': package['name'], 'ecosystem': 'crates.io'}
            if not source.startswith('registry+'):
                unscanned.append(item)
                continue
            packages.append(dict(item, version=package['version']))
    return packages, unscanned


def key(item):
    return hashlib.sha256(json.dumps([item['file'], item['ecosystem'], item['name']]).encode()).hexdigest()


def scan(root):
    packages, unscanned = inventory(root)
    findings, details = [], {}
    for offset in range(0, len(packages), 100):
        batch = packages[offset:offset + 100]
        queries = [{'package': {'name': p['name'], 'ecosystem': p['ecosystem']},
                    'version': p['version']} for p in batch]
        results = api('https://api.osv.dev/v1/querybatch', 'POST', {'queries': queries})['results']
        if len(results) != len(batch):
            raise ValueError('Incomplete vulnerability response')
        for package, result in zip(batch, results):
            if result.get('error'):
                raise ValueError('Vulnerability query failed')
            if result.get('next_page_token'):
                raise ValueError('Vulnerability response truncated; manual investigation required')
            for entry in result.get('vulns', []):
                identifier = entry['id']
                if identifier not in details:
                    details[identifier] = api(f'https://api.osv.dev/v1/vulns/{identifier}')
                advisory = details[identifier]
                if advisory.get('withdrawn'):
                    continue
                aliases = sorted(set([identifier] + advisory.get('aliases', [])))
                fixed = sorted({e['fixed'] for a in advisory.get('affected', [])
                    if a.get('package', {}).get('name') == package['name']
                    for r in a.get('ranges', []) for e in r.get('events', []) if 'fixed' in e})
                findings.append(dict(package, id=identifier, aliases=aliases, fixed=fixed,
                    severity=advisory.get('database_specific', {}).get('severity', 'UNKNOWN'),
                    summary=advisory.get('summary', ''), url=f'https://osv.dev/vulnerability/{identifier}'))
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    return {'schema': 1, 'sha': sha, 'complete': True, 'packages': packages,
            'unscanned': unscanned, 'findings': findings}


def new_findings(base, head):
    old = {(key(f), a) for f in base['findings'] for a in f['aliases']}
    return [f for f in head['findings'] if not any((key(f), a) in old for a in f['aliases'])]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=pathlib.Path)
    parser.add_argument('output', type=pathlib.Path)
    parser.add_argument('--baseline', type=pathlib.Path)
    args = parser.parse_args()
    report = scan(args.root.resolve())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Scanned {len(report["packages"])} resolved versions; {len(report["findings"])} advisory matches; '
          f'{len(report["unscanned"])} local/git dependencies require manual assessment')
    if args.baseline:
        additions = new_findings(json.loads(args.baseline.read_text(encoding='utf-8')), report)
        if additions:
            raise SystemExit(f'New dependency vulnerabilities: {len(additions)}; see JSON report')
