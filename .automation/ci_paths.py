"""Path rules for the CNB pull_request pipelines.

`trigger` decides whether a stage of the Flutter pipeline runs; `reuse` lets a controller
sync-main merge keep the CI verdict of the requirement head it merged. Both print why and
exit with SKIP to skip; any other status, a crash included, runs the stage. `base` prints
where an owner/** push build measures its changes from (see push_base).
"""
import os
import re
import subprocess
import sys

CNB_YML = '.cnb.yml'
FLUTTER = 'Flutter and Android requirement tests'
SKIP = 3
# git's empty tree: diffing from it lists every tracked path, so nothing can be skipped.
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
CONTROLLER = 'FlClash-Actor: controller'

# Paths that start each Flutter pipeline stage; a trailing '/' names a directory.
# .cnb.yml counts only when the Flutter pipeline's own block changed.
TRIGGERS = {
    'flutter': ('lib/', 'test/', 'android/', 'arb/', 'assets/', 'plugins/', 'pubspec.yaml', 'pubspec.lock',
                'analysis_options.yaml', 'lint_options.yaml', 'build.yaml', '.cnb/Dockerfile', CNB_YML),
    'android': ('android/', 'core/', 'pubspec.yaml', 'pubspec.lock', '.cnb/Dockerfile', CNB_YML),
    'govet': ('core/', 'build_config.yaml', '.cnb/Dockerfile', CNB_YML),
}

# Reuse whitelist. NEUTRAL paths feed no pipeline. Each area feeds pipelines no other area feeds.
# Any other path (android/, pubspec, lockfiles, .cnb*, .automation/, tool/, plugins/, build configs)
# is a shared build input, so touching it on either side reruns every pipeline; android/ feeds both
# the flutter and the android stages, so it cannot be an area of its own.
NEUTRAL = ('docs/', 'snapshots/', 'LICENSE')
AREAS = {
    'dart': ('lib/', 'test/', 'arb/', 'assets/'),
    'native': ('core/',),
    'rust': ('services/',),
    'desktop': ('linux/', 'macos/', 'windows/'),
}
# A pipeline value that is a YAML alias pulls in text from outside the Flutter block.
ALIAS = re.compile(r'^\s*(-\s+)?([\w"\'-]+:\s+)?\*[\w-]+\s*$|<<:', re.M)


def _match(path, entries):
    return any(path.startswith(entry) if entry.endswith('/') else path == entry for entry in entries)


def area(path):
    """Return 'neutral', the whitelisted area of path, or None for a shared build input."""
    if _match(path, NEUTRAL) or ('/' not in path and path.endswith('.md')):
        return 'neutral'
    return next((name for name, entries in AREAS.items() if _match(path, entries)), None)


def reusable(main_paths, own_paths):
    """True when both sides stay inside the whitelist and touch no area in common."""
    sides = []
    for paths in (main_paths, own_paths):
        names = {area(path) for path in paths}
        if None in names:
            return False
        sides.append(names - {'neutral'})
    return bool(main_paths) and not sides[0] & sides[1]


def flutter_block(source):
    """Return the Flutter pipeline's lines of .cnb.yml, or None when it cannot be located."""
    lines = source.split('\n')
    start = next((i for i, line in enumerate(lines) if line.strip() == f'- name: {FLUTTER}'), None)
    if start is None:
        # An anchored entry puts `- &name` on its own line and the name on the next one.
        start = next((i - 1 for i, line in enumerate(lines) if i and line.strip() == f'name: {FLUTTER}'
                      and re.fullmatch(r'\s*- &[\w-]+', lines[i - 1])), None)
    if start is None:
        return None
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= indent), len(lines))
    return '\n'.join(lines[start:end]).rstrip()


def flutter_definition_changed(old, new):
    blocks = [flutter_block(old or ''), flutter_block(new or '')]
    if None in blocks or any(ALIAS.search(block) for block in blocks):
        return old != new
    return blocks[0] != blocks[1]


def triggers(stage, changed, old_cnb, new_cnb):
    """True when this Flutter pipeline stage must run for these changed paths."""
    for path in changed:
        if path == CNB_YML:
            if flutter_definition_changed(old_cnb, new_cnb):
                return True
        elif _match(path, TRIGGERS[stage]):
            return True
    return False


def run_git(*args, check=True, env=None):
    """control.git without the controller's imports: check=True returns stripped stdout."""
    result = subprocess.run(['git', *args], env=env, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f'git {args[0]} failed: {result.stderr[-500:]}')
    return result.stdout.strip() if check else result


def sync_parents(head, git, branch):
    """Return [requirement parent, main parent] when head is the controller's sync-main merge."""
    parents = git('rev-list', '--parents', '-n', '1', head).split()[1:]
    if len(parents) != 2 or not re.fullmatch(r'automation/req-\d+', branch):
        return None
    lines = [line.strip() for line in git('log', '-1', '--format=%B', head).splitlines()]
    if not lines or lines[0] != f'Merge main into {branch}' or CONTROLLER not in lines:
        return None
    return parents


def reuse_claim(head, git, branch):
    """Return the requirement parent whose CI verdict head may keep, or ''."""
    parents = sync_parents(head, git, branch)
    if not parents:
        return ''
    own, main = parents
    merged = git('merge-tree', '--write-tree', own, main, check=False)
    if merged.returncode or merged.stdout.split()[:1] != [git('rev-parse', head + '^{tree}')]:
        return ''
    base = git('merge-base', own, main)
    changed = {tip: git('diff', '--name-only', base, tip).splitlines() for tip in parents}
    return own if reusable(changed[main], changed[own]) else ''


def hooked(head, git):
    """True when head's own .cnb.yml runs the reuse check, so its pipelines may have skipped."""
    shown = git('show', f'{head}:{CNB_YML}', check=False)
    return shown.returncode == 0 and 'ci_paths.py reuse' in shown.stdout


def push_base(git=run_git):
    """Return the merge-base of HEAD with main for a push build, or EMPTY_TREE when it is unknown.

    A push carries no pull request target. Its changes are measured against main, not against the
    previous push, so a branch pushed in several steps still runs every stage its whole diff feeds.
    """
    try:
        git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main')
        return git('merge-base', 'refs/remotes/origin/main', 'HEAD') or EMPTY_TREE
    except Exception:  # Without a base every path counts as changed.
        return EMPTY_TREE


def main(argv):
    try:
        if argv[1:2] == ['base']:
            print(push_base())
            return 0
        if argv[1:2] == ['trigger']:
            # A push build has no CNB_PULL_REQUEST_TARGET_SHA, so the stage passes an empty base.
            stage, base = argv[2], argv[3] or push_base()
            changed = run_git('diff', '--name-only', base, 'HEAD').splitlines()
            old = run_git('show', f'{base}:{CNB_YML}', check=False)
            with open(CNB_YML, encoding='utf-8') as handle:
                new = handle.read()
            if triggers(stage, changed, old.stdout if old.returncode == 0 else '', new):
                return 0
            print(f'Skipped: no changes that feed the {stage} stage')
            return SKIP
        if argv[1:2] == ['reuse']:
            branch = os.environ.get('CNB_PULL_REQUEST_BRANCH', '').removeprefix('refs/heads/')
            head = os.environ.get('CNB_PULL_REQUEST_SHA') or 'HEAD'
            if run_git('rev-parse', 'HEAD^{tree}') != run_git('rev-parse', head + '^{tree}'):
                return 0
            reused = reuse_claim(head, run_git, branch)
            if reused:
                print(f'Reused CI of {reused[:12]}: {head[:12]} only merges main, and main and the '
                      'requirement share no build input. Main CI reruns after the merge.')
                return SKIP
            return 0
    except Exception as error:  # A failed check must run the stage, never skip it.
        print(f'Path check failed ({type(error).__name__}); running the stage')
        return 0
    print('usage: ci_paths.py trigger <flutter|android|govet> <base> | ci_paths.py reuse | ci_paths.py base')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
