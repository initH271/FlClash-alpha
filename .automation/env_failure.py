"""Report a network environment failure without claiming the scan found anything.

A scan that cannot reach its advisory source is neither clean nor exposed, so it
leaves a machine-readable marker on stdout and exits with its own code. Callers
that only look for "non-zero" still fail.
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
