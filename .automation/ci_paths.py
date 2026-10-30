"""Path rules for the CNB pull_request pipelines.

`trigger` decides whether a stage of the Flutter pipeline runs. It prints why and exits with
SKIP to skip; any other status, a crash included, runs the stage.
"""
import re
import subprocess
import sys

CNB_YML = '.cnb.yml'
FLUTTER = 'Flutter and Android requirement tests'
SKIP = 3

# Paths that start each Flutter pipeline stage; a trailing '/' names a directory.
# .cnb.yml counts only when the Flutter pipeline's own block changed.
TRIGGERS = {
    'flutter': ('lib/', 'test/', 'android/', 'arb/', 'assets/', 'plugins/', 'pubspec.yaml', 'pubspec.lock',
                'analysis_options.yaml', 'lint_options.yaml', 'build.yaml', '.cnb/Dockerfile', CNB_YML),
    'android': ('android/', 'core/', 'pubspec.yaml', 'pubspec.lock', '.cnb/Dockerfile', CNB_YML),
    'govet': ('core/', 'build_config.yaml', '.cnb/Dockerfile', CNB_YML),
}

# A pipeline value that is a YAML alias pulls in text from outside the Flutter block.
ALIAS = re.compile(r'^\s*(-\s+)?([\w"\'-]+:\s+)?\*[\w-]+\s*$|<<:', re.M)


def _match(path, entries):
    return any(path.startswith(entry) if entry.endswith('/') else path == entry for entry in entries)


def flutter_block(source):
    """Return the Flutter pipeline's lines of .cnb.yml, or None when it cannot be located."""
    lines = source.split('\n')
    start = next((i for i, line in enumerate(lines) if line.strip() == f'- name: {FLUTTER}'), None)
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


def main(argv):
    try:
        if argv[1:2] == ['trigger']:
            stage, base = argv[2], argv[3]
            changed = run_git('diff', '--name-only', base, 'HEAD').splitlines()
            old = run_git('show', f'{base}:{CNB_YML}', check=False)
            with open(CNB_YML, encoding='utf-8') as handle:
                new = handle.read()
            if triggers(stage, changed, old.stdout if old.returncode == 0 else '', new):
                return 0
            print(f'Skipped: no changes that feed the {stage} stage')
            return SKIP
    except Exception as error:  # A failed check must run the stage, never skip it.
        print(f'Path check failed ({type(error).__name__}); running the stage')
        return 0
    print('usage: ci_paths.py trigger <flutter|android|govet> <base>')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
