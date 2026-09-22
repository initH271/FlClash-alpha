import argparse
import hashlib
import json
import os
import pathlib
import re
import ssl
import subprocess
import time
import tomllib
import urllib.error

from control import api
from security_groups import GROUPS, group_for

LOCKS = ('services/helper/Cargo.lock', 'plugins/rust_api/rust/Cargo.lock')


def osv_query(url, method='GET', data=None):
    if not url.startswith('https://api.osv.dev/v1/') or method not in ('GET', 'POST'):
        raise ValueError('Only OSV read queries may be retried')
    for attempt in range(3):
        try:
            return api(url, method, data)
        except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLEOFError) as error:
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            if not isinstance(reason, (TimeoutError, ConnectionError, ssl.SSLEOFError)) or attempt == 2:
                raise
            print(f'Transient OSV connection failure; retry {attempt + 1}/2')
            time.sleep(2 ** (attempt + 1))


def json_stream(text):
    decoder = json.JSONDecoder()
    while text.strip():
        value, end = decoder.raw_decode(text.lstrip())
        yield value
        text = text.lstrip()[end:]


VERSION = re.compile(r'(\d+)\.(\d+)\.(\d+)')

# Pins that decide which Go toolchain builds core. `GOVERSION` only reports the
# ambient toolchain, which is identical for a baseline and a PR scan that run in
# the same image, so repairs must be judged on the pinned versions in the tree.
TOOLCHAIN_PINS = (
    ('.cnb.yml', re.compile(r'image:\s*golang:(\d+\.\d+\.\d+)')),
    ('.cnb/Dockerfile', re.compile(r'/dl/go(\d+\.\d+\.\d+)\.linux-')),
    ('.github/workflows/build.yaml', re.compile(r"go-version:\s*'?([\w.]+)'?")),
    ('.github/workflows/security.yaml', re.compile(r"go-version:\s*'?([\w.]+)'?")),
    ('.github/upstream-build.yaml', re.compile(r"GO_VERSION:\s*'?([\w.]+)'?")),
)


def parsed_version(value):
    match = VERSION.search(value or '')
    return tuple(int(part) for part in match.groups()) if match else None


def core_toolchain(root):
    pins = {}
    for filename, pattern in TOOLCHAIN_PINS:
        path = root / filename
        if not path.is_file():
            continue
        # Placeholder-only pins such as `${{ env.GO_VERSION }}` are ignored so a
        # workflow still resolves to its literal GO_VERSION declaration.
        versions = [v for v in pattern.findall(path.read_text(encoding='utf-8')) if not v.startswith('$')]
        if versions:
            pins[filename] = sorted(versions)
    declared = [v for versions in pins.values() for v in versions]
    # A repair is only credited when the pinned versions are readable and move
    # forward, so lowering or breaking a pin cannot satisfy the gate.
    known = [tuple(map(int, v.split('.'))) for v in declared if parsed_version(v)]
    version = '.'.join(map(str, max(known))) if known else ''
    return {'version': version, 'pins': pins}


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
        results = osv_query('https://api.osv.dev/v1/querybatch', 'POST', {'queries': queries})['results']
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
                    details[identifier] = osv_query(f'https://api.osv.dev/v1/vulns/{identifier}')
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
            'unscanned': unscanned, 'findings': findings,
            'toolchain': {'core/go.mod': core_toolchain(root)}}


def new_findings(base, head):
    old = {(key(f), a) for f in base['findings'] for a in f['aliases']}
    return [f for f in head['findings'] if not any((key(f), a) in old for a in f['aliases'])]


def require_clean_group(report, prefix):
    if not re.fullmatch('[0-9a-f]{12}', prefix):
        raise ValueError('Invalid security repair group')
    unresolved = [f for f in report['findings'] + report['unscanned'] if key(f).startswith(prefix)]
    if unresolved:
        raise ValueError('Target dependency still has advisories or an unindexed replacement: '
                         + ', '.join(f.get('id', f['name']) for f in unresolved))


def toolchain_moved(base, head):
    before, after = base.get('toolchain', {}), head.get('toolchain', {})
    if not before or set(before) != set(after):
        return False
    if not base.get('packages') or not head.get('packages'):
        raise ValueError('Grouped repairs require both scans to index the Go module')
    return all(version_advanced(before[path], entry) for path, entry in after.items())


def version_advanced(before, after):
    # "version" is the highest pin, so it can stay level while a lower pin drops;
    # every readable pin must therefore be present and higher than before.
    # A pin file that exists only on the repair side was not in that comparison,
    # so it must still reach the new version.
    old, new = parsed_version(before.get('version')), parsed_version(after.get('version'))
    if not old or not new or new <= old:
        return False
    before_pins = before.get('pins', {})
    after_pins = after.get('pins', {})
    if not before_pins or not all(
        pin_advanced(before_pins[name], after_pins.get(name, [])) for name in before_pins
    ):
        return False
    return all(pin_at_least(after_pins[name], new) for name in set(after_pins) - set(before_pins))


def pin_advanced(before, after):
    was = [parsed_version(v) for v in before]
    now = [parsed_version(v) for v in after]
    return bool(was) and bool(now) and min(now) > min(was)


def pin_at_least(versions, minimum):
    parsed = [parsed_version(value) for value in versions]
    return bool(parsed) and all(item is not None and item >= minimum for item in parsed)


def require_group_progress(base, head, group):
    if group not in GROUPS:
        raise ValueError('Unknown repair group')
    before = [f for f in base['findings'] if group_for(f) == group]
    after = [f for f in head['findings'] if group_for(f) == group]
    if new_findings({'findings': before}, {'findings': after}):
        raise ValueError('Grouped repair introduces new vulnerabilities')
    indexed = {key(p) for p in base['packages'] if group_for(p) == group}
    if any(key(p) in indexed for p in head['unscanned']):
        raise ValueError('An unindexed replacement cannot count as a repair')
    advanced = group == 'go-core' and toolchain_moved(base, head)
    remaining = {(key(f), alias) for f in after for alias in f['aliases']}
    improved = any(not any((key(f), alias) in remaining for alias in f['aliases']) for f in before)
    if not improved and not advanced:
        raise ValueError('Grouped repair must remove at least one existing advisory match or '
                         'move the Go toolchain forward')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=pathlib.Path)
    parser.add_argument('output', type=pathlib.Path)
    parser.add_argument('--baseline', type=pathlib.Path)
    parser.add_argument('--repair-branch', default='')
    args = parser.parse_args()
    report = scan(args.root.resolve())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Scanned {len(report["packages"])} resolved versions; {len(report["findings"])} advisory matches; '
          f'{len(report["unscanned"])} local/git dependencies require manual assessment')
    branch = args.repair_branch.removeprefix('refs/heads/')
    if branch.startswith('security/fix-'):
        require_clean_group(report, branch.removeprefix('security/fix-'))
    if branch.startswith('security/group-'):
        if not args.baseline:
            raise ValueError('Grouped repairs require a baseline scan')
        require_group_progress(json.loads(args.baseline.read_text(encoding='utf-8')),
                               report, branch.removeprefix('security/group-'))
    if args.baseline:
        additions = new_findings(json.loads(args.baseline.read_text(encoding='utf-8')), report)
        if additions:
            raise SystemExit(f'New dependency vulnerabilities: {len(additions)}; see JSON report')
