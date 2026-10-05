"""Generate Android alpha release notes from the Git range of one release.

The notes for a build describe what that build changed relative to the
previous published alpha, so they come from the commit range and never from
the accumulated `.github/release-notes.md`, which carries the whole history.
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

# Only these subject types reach the notes; `docs`, `chore`, `ci`, `test` and
# `build` are maintenance and would drown the user-visible changes.
DEFAULT_TYPES = {'feat': 'feat', 'fix': 'fix', 'perf': 'perf', 'revert': 'revert'}

# `Changelog` flags, `Changelog-Type` overrides the group, `BREAKING CHANGE`
# always adds a breaking entry.
CHANGELOG_SKIP = 'skip'

TAG_PATTERN = re.compile(r'^alpha-(\d+)\.(\d+)\.(\d+)-(\d+)$')

SUBJECT_PATTERN = re.compile(
    r'^([a-z]+)(?:\(([^)]*)\))?(!)?:[ \t]+(.+)$',
)

TRAILER_PATTERN = re.compile(
    r'^(BREAKING[ -]CHANGE|Changelog(?:-[A-Za-z0-9-]+)?|Breaking-[A-Za-z0-9-]+)'
    r':[ \t]*(.*)$',
)

# Any trailer-shaped line ends the trailer being accumulated, so a
# `Co-authored-by:` after a `Changelog:` footer isn't glued onto its text.
GENERIC_TRAILER_PATTERN = re.compile(
    r'^(?:[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+|Refs|Fixes|Closes):[ \t]*',
    re.IGNORECASE,
)

SECTION_TITLES = {
    'breaking': 'Breaking',
    'feat': 'New',
    'fix': 'Fixes',
    'perf': 'Performance',
    'revert': 'Reverts',
}

SECTION_ORDER = ('breaking', 'feat', 'fix', 'perf', 'revert')


class NotesError(Exception):
    pass


def git(*args, cwd):
    result = subprocess.run(
        ['git', *args], cwd=cwd, text=True, capture_output=True,
    )
    if result.returncode:
        raise NotesError(
            f'git {" ".join(args)} failed ({result.returncode}): '
            f'{result.stderr.strip()}'
        )
    return result.stdout


@dataclass(frozen=True)
class Commit:
    subject: str
    body: str


def parse_alpha_builds(tag_names):
    """Map `alpha-<version>-<build>` tag names to their build number."""
    builds = {}
    for name in tag_names:
        match = TAG_PATTERN.match(name)
        if match:
            builds[name] = int(match.group(4))
    return builds


def list_tag_names(repo):
    return [line.strip() for line in git('tag', '--list', cwd=repo).splitlines() if line.strip()]


def tag_builds(repo):
    return parse_alpha_builds(list_tag_names(repo))


def tag_ref(repo, name):
    """Return `name` as a full refname when it resolves, else None.

    Some checkouts reply to `git rev-parse` with a symbolic refname instead of
    an object id, so the result is checked rather than trusted.
    """
    full = f'refs/tags/{name}'
    try:
        resolved = git('rev-parse', full, cwd=repo).strip()
    except NotesError:
        return None
    if not resolved or resolved.startswith('refs/') or resolved.endswith('^{}'):
        return None
    return full


def reachable(ref, repo):
    result = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', ref, 'HEAD'],
        cwd=repo, text=True, capture_output=True,
    )
    return result.returncode == 0


def select_base(tags, build, repo, explicit=None):
    """Pick the previous alpha: reachable and strictly smaller build number.

    Tags that are unreachable, carry a larger build number, or are not
    `alpha-<version>-<build>` at all (stable `v*`, beta, arbitrary) are
    ignored. The winner is the largest remaining build.
    """
    if explicit:
        match = TAG_PATTERN.match(explicit)
        if not match:
            raise NotesError(
                f'--base {explicit!r} is not an alpha-<version>-<build> tag'
            )
        candidate_build = int(match.group(4))
        candidate = tag_ref(repo, explicit)
        if candidate is None:
            raise NotesError(f'--base tag {explicit!r} does not exist')
        if candidate_build >= build:
            raise NotesError(
                f'--base build {candidate_build} is not smaller than {build}'
            )
        if not reachable(candidate, repo):
            raise NotesError(f'--base tag {explicit!r} is not reachable from HEAD')
        return candidate, candidate_build

    eligible = []
    for name, candidate_build in tags.items():
        if candidate_build >= build:
            continue
        ref = tag_ref(repo, name)
        if ref is None or not reachable(ref, repo):
            continue
        eligible.append((candidate_build, name, ref))
    if not eligible:
        raise NotesError(
            f'no reachable alpha tag with a build number below {build}; '
            'refusing to fall back to the full history'
        )
    candidate_build, name, ref = max(eligible)
    return ref, candidate_build


def range_commits(base_ref, repo):
    """Every commit reachable from HEAD but not from the base tag.

    Merge commits are included on purpose: a PR whose commits were rewritten
    before merging keeps its `Changelog:` text only on the merge commit.
    """
    output = git(
        'log', '--format=%s%x00%b%x01', f'{base_ref}..HEAD', cwd=repo,
    )
    commits = []
    for chunk in output.split('\x01'):
        chunk = chunk.strip('\n')
        if not chunk:
            continue
        subject, body = chunk.split('\x00', 1)
        commits.append(Commit(subject=subject, body=body))
    return commits


def read_trailers(body):
    trailers = {}
    current = None
    for line in body.split('\n'):
        match = TRAILER_PATTERN.match(line)
        if match:
            current = match.group(1).replace('BREAKING-CHANGE', 'BREAKING CHANGE')
            trailers[current] = match.group(2).strip()
            continue
        if current is None:
            continue
        if GENERIC_TRAILER_PATTERN.match(line):
            current = None
            continue
        continuation = line.strip()
        if not continuation:
            current = None
            continue
        trailers[current] = f'{trailers[current]} {continuation}'.strip()
    return trailers


def capitalise(value):
    return value if not value else value[0].upper() + value[1:]


def entry_text(trailer, description):
    return capitalise(description) if not trailer else trailer


def parse_commit(commit, allowed_types):
    # Merge commits carry no conventional subject, but a rewritten PR keeps its
    # only `Changelog:` text there, so trailers are read before the subject is
    # required. A commit without either contributes nothing.
    match = SUBJECT_PATTERN.match(commit.subject.strip())
    subject_type, bang, description = '', False, ''
    if match:
        subject_type, _, bang, description = match.groups()
        description = description.strip()

    trailers = read_trailers(commit.body)
    changelog = trailers.get('Changelog')
    if changelog is not None and changelog.lower() == CHANGELOG_SKIP:
        return []
    if not match and changelog is None and 'BREAKING CHANGE' not in trailers:
        return []

    items = []
    breaking = trailers.get('BREAKING CHANGE')
    if bang or breaking is not None:
        items.append(('breaking', entry_text(breaking, description)))

    override = trailers.get('Changelog-Type')
    group = override if override in SECTION_TITLES else allowed_types.get(subject_type)
    if group is None and 'Changelog' in trailers:
        group = 'feat'
    if group is not None and group in SECTION_TITLES:
        items.append((group, entry_text(changelog, description)))
    return items


def dedupe(items):
    """Drop repeats in commit order, newest first."""
    seen = set()
    unique = []
    for group, text in items:
        key = re.sub(r'\s+', ' ', text).strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append((group, text))
    return unique


def render(version, build, commits, allowed_types=DEFAULT_TYPES):
    items = []
    for commit in commits:
        items.extend(parse_commit(commit, allowed_types))
    items = dedupe(items)

    lines = [f'FlClash-alpha {version}（构建 {build}）', '']
    if items:
        for group in SECTION_ORDER:
            entries = [text for item_group, text in items if item_group == group]
            if not entries:
                continue
            lines.append(f'### {SECTION_TITLES[group]}')
            lines.append('')
            lines.extend(f'- {text}' for text in entries)
            lines.append('')
    else:
        lines.extend(['本版没有用户可见的变化。', ''])

    return '\n'.join(lines).rstrip('\n') + '\n'


def generate(repo, version, build, explicit_base=None, allowed_types=DEFAULT_TYPES):
    base_ref, base_build = select_base(tag_builds(repo), build, repo, explicit_base)
    commits = range_commits(base_ref, repo)
    base_name = base_ref.removeprefix('refs/tags/')
    base_sha = git('rev-parse', f'{base_ref}^{{commit}}', cwd=repo).strip()
    source_sha = git('rev-parse', 'HEAD', cwd=repo).strip()
    notes = render(version, build, commits, allowed_types)
    return {
        'notes': notes,
        'base_tag': base_name,
        'base_build': base_build,
        'base_sha': base_sha,
        'source_sha': source_sha,
        'commits': len(commits),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='.', help='Git working tree to read')
    parser.add_argument('--version', required=True)
    parser.add_argument('--build', required=True, type=int)
    parser.add_argument('--base', default=None, help='Explicit alpha tag for a dry run')
    parser.add_argument('--output', default='-')
    args = parser.parse_args(argv)

    try:
        result = generate(args.repo, args.version, args.build, args.base)
    except NotesError as error:
        print(f'release notes failed: {error}', file=sys.stderr)
        return 1

    if args.output == '-':
        sys.stdout.write(result['notes'])
    else:
        with open(args.output, 'w', encoding='utf-8') as handle:
            handle.write(result['notes'])
    print(
        f"notes base {result['base_tag']} ({result['base_sha']}) -> "
        f"{result['source_sha']} over {result['commits']} commits",
        file=sys.stderr,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
