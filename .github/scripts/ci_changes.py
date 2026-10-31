"""Decide which ci.yml jobs a pull request needs.

A path no rule names runs every job, so a new kind of file costs time, never coverage.
"""
import os
import subprocess
import sys

JOBS = ('automation', 'go', 'rust', 'flutter', 'android_unit', 'android_build')
# Nothing compiles or tests these. A trailing '/' names a directory; *.md counts only at the root.
NEUTRAL = ('docs/', 'snapshots/', 'LICENSE')
# First match wins. Every path that is not neutral also runs the automation tests: they take
# seconds and read files from all over the repository.
RULES = (
    (('.github/workflows/ci.yml',), JOBS),
    (('.automation/', '.cnb/', '.cnb.yml', '.github/workflows/'), ()),
    (('core/', 'build_config.yaml', '.gitmodules'), ('go', 'android_unit', 'android_build')),
    (('services/',), ('rust',)),
    (('android/',), ('flutter', 'android_unit', 'android_build')),
    (('lib/', 'arb/', 'assets/', 'shaders/'), ('flutter', 'android_build')),
    (('test/',), ('flutter',)),
)


def _match(path, entries):
    return any(path.startswith(entry) if entry.endswith('/') else path == entry for entry in entries)


def needed_jobs(paths):
    """Return the set of JOBS these changed paths need."""
    jobs = set()
    for path in paths:
        if _match(path, NEUTRAL) or ('/' not in path and path.endswith('.md')):
            continue
        jobs.add('automation')
        rule = next((targets for entries, targets in RULES if _match(path, entries)), JOBS)
        jobs.update(rule)
    return jobs


def changed_paths(base, head, cwd=None):
    """Both sides of a rename count: moving a file out of core/ still changes core/."""
    output = subprocess.run(['git', 'diff', '--no-renames', '--name-only', '-z', base, head],
                            cwd=cwd, check=True, capture_output=True, text=True).stdout
    return [path for path in output.split('\0') if path]


def main():
    jobs = set(JOBS)
    if os.environ.get('GITHUB_EVENT_NAME') == 'pull_request':
        # The pull_request checkout is a merge commit whose first parent is the target branch.
        try:
            paths = changed_paths('HEAD^1', 'HEAD')
        except (OSError, subprocess.CalledProcessError) as error:
            print(f'Running every job, cannot list changes: {error}', file=sys.stderr)
        else:
            jobs = needed_jobs(paths)
            print(f'{len(paths)} changed paths')
    lines = [f'{job}={"true" if job in jobs else "false"}' for job in JOBS]
    print('\n'.join(lines))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
