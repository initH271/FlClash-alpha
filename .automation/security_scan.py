import argparse
import hashlib
import json
import math
import os
import pathlib
import socket
import ssl
import subprocess
import sys
import time
import tomllib
import urllib.error

from control import HttpStatusError, api
from env_failure import EXIT_CODE, EnvironmentFailure, line

LOCKS = ('services/helper/Cargo.lock', 'plugins/rust_api/rust/Cargo.lock')

RETRY_DELAYS = (5, 20, 60, 180)
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
TRANSIENT = (TimeoutError, ConnectionError, ssl.SSLEOFError, socket.gaierror)
REQUEST_TIMEOUT = 20
DEFAULT_BUDGET = 300


def deadline():
    """Retries must end before the CI stage does, so the budget is handed down
    through the environment and defaults to a fixed window."""
    configured = os.getenv('FLCLASH_NETWORK_DEADLINE')
    # Monotonic seconds cannot be compared with the Unix timestamp in the
    # environment, so the budget is converted into the monotonic scale here.
    remaining = DEFAULT_BUDGET if not configured else max(0, float(configured) - time.time())
    return time.monotonic() + remaining


def timeout_for(until):
    """Whole seconds left before the deadline, floored so the request ends inside it."""
    return max(1, min(REQUEST_TIMEOUT, math.floor(until - time.monotonic())))


def retryable(error):
    if isinstance(error, HttpStatusError):
        return error.code in RETRYABLE_STATUS
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return isinstance(reason, TRANSIENT)


def osv_query(url, method='GET', data=None, until=None):
    if not url.startswith('https://api.osv.dev/v1/') or method not in ('GET', 'POST'):
        raise ValueError('Only OSV read queries may be retried')
    until = deadline() if until is None else until
    attempts = 0
    for delay in (0, *RETRY_DELAYS):
        # The wait is taken first, so the timeout below is what the request
        # actually has left. A wait that would leave less than a second for it
        # ends the retries instead of pushing one request past the deadline.
        if delay and delay + 1 > until - time.monotonic():
            break
        if delay:
            print(f'Transient OSV connection failure; retry after {delay}s')
            time.sleep(delay)
        attempts += 1
        try:
            return api(url, method, data, timeout=timeout_for(until))
        except (TRANSIENT + (urllib.error.URLError, HttpStatusError)) as error:
            if not retryable(error):
                raise
            last = error
    # An unreachable advisory source says nothing about the dependencies, so it
    # must never leave a report behind that reads as a clean scan.
    raise EnvironmentFailure('osv-unreachable',
                             {'url': url, 'attempts': attempts, 'error': str(last)[:300]})


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


def scan(root, until=None):
    packages, unscanned = inventory(root)
    until = deadline() if until is None else until
    findings, details = [], {}
    for offset in range(0, len(packages), 100):
        batch = packages[offset:offset + 100]
        queries = [{'package': {'name': p['name'], 'ecosystem': p['ecosystem']},
                    'version': p['version']} for p in batch]
        results = osv_query('https://api.osv.dev/v1/querybatch', 'POST', {'queries': queries}, until)['results']
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
                    details[identifier] = osv_query(f'https://api.osv.dev/v1/vulns/{identifier}', until=until)
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


def head_sha(root):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=pathlib.Path)
    parser.add_argument('output', type=pathlib.Path)
    parser.add_argument('--baseline', type=pathlib.Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    until = deadline()
    try:
        report = scan(root, until)
    except EnvironmentFailure as error:
        # Same non-zero shape as a finding for anything that only reads the exit
        # code, but the marker keeps it from being recorded as one.
        message = line(error.kind, sha=head_sha(root), **error.detail)
        print(message, flush=True)
        return EXIT_CODE
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Scanned {len(report["packages"])} resolved versions; {len(report["findings"])} advisory matches; '
          f'{len(report["unscanned"])} local/git dependencies require manual assessment')
    if args.baseline:
        additions = new_findings(json.loads(args.baseline.read_text(encoding='utf-8')), report)
        if additions:
            print(f'New dependency vulnerabilities: {len(additions)}; see JSON report')
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
