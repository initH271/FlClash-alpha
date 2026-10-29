"""Report a network environment failure without claiming the scan found anything.

A scan that cannot reach its advisory source is neither clean nor exposed, so it
leaves a machine-readable marker on stdout and exits with its own code. Callers
that only look for "non-zero" still fail, while the controller can tell the two
apart and retry instead of opening or closing security work.
"""

import json

MARKER = 'FLCLASH_ENV_FAILURE'
EXIT_CODE = 75


class EnvironmentFailure(RuntimeError):
    def __init__(self, kind, detail):
        super().__init__(f'{kind}: {detail}')
        self.kind = kind
        self.detail = detail


def line(kind, **detail):
    return MARKER + ' ' + json.dumps({'kind': kind, **detail}, ensure_ascii=False, sort_keys=True)


def parse(text):
    marker = MARKER + ' '
    results = []
    for row in text.splitlines():
        if not row.startswith(marker):
            continue
        try:
            payload = json.loads(row[len(marker):])
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get('kind'), str):
            results.append(payload)
    return results
