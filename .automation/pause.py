from control import POLICY

WORDS = ('HOLD', 'RELEASE')


def command(item):
    """Return the HOLD or RELEASE the owner wrote as the whole comment, else ''."""
    author = item.get('author') or {}
    if author.get('username') != POLICY['approver'] or author.get('is_npc') is not False:
        return ''
    body = (item.get('body') or '').strip()
    return body if body in WORDS else ''


def held(comments):
    """Return when the owner last took the branch, or '' while it is not taken."""
    owner = [item for item in comments or []
             if command(item) and (item.get('author') or {}).get('username') == POLICY['approver']]
    owner.sort(key=lambda item: item.get('created_at') or '')
    return owner[-1].get('created_at', '') if owner and command(owner[-1]) == 'HOLD' else ''


def paused(scope, branch='', comments=None, now=None):
    """Return what pauses an action, or None.

    'branch' covers the actions that only write the requirement branch; 'main' covers
    the ones that join main or refresh a branch waiting to merge. Only HOLD is wired in
    so far, so both scopes answer the same here.
    """
    if scope not in ('branch', 'main'):
        raise ValueError('scope must be branch or main')
    since = held(comments or [])
    if since and (branch or '').startswith('automation/req-'):
        return {'source': 'hold', 'since': since, 'branch': branch}
    return None
