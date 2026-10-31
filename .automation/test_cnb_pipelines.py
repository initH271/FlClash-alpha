import pathlib
import re
import sys
import unittest
from unittest.mock import patch

try:
    import yaml
except ImportError:
    yaml = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
CNB = ROOT / '.cnb.yml'
HOURLY = 'crontab: 7 * * * *'
MIRROR = 'Mirror signed GitHub release to CNB'
# CI runs on GitHub. CNB keeps the download mirror, the NPC review, the upstream NPC analysis and cloud development.
EVENTS = ['api_trigger', 'web_trigger', 'api_trigger_npc_review', 'api_trigger_npc_upstream', 'vscode']


# A mapping entry: a plain or quoted key followed by a colon that ends the line or precedes a space.
MAPPING = re.compile(r'("[^"]*"|\'[^\']*\'|[^\s:][^:]*):(\s|$)')


def _indent(line):
    return len(line) - len(line.lstrip(' '))


def _scalar(text):
    text = text.strip()
    if text.startswith('{') and text.endswith('}'):
        pairs = (pair.split(':', 1) for pair in text[1:-1].split(',') if pair.strip())
        return {key.strip(): _scalar(value) for key, value in pairs}
    if text.isdigit():
        return int(text)
    if text in ('true', 'false'):
        return text == 'true'
    if len(text) > 1 and text[0] == text[-1] and text[0] in '\'"':
        return text[1:-1]
    return text


def _key(text):
    """Split 'key: value' where the key may be quoted and contain colons."""
    if text[0] in '\'"':
        end = text.index(text[0], 1)
        return text[1:end], text[end + 1:].lstrip(':').strip()
    key, _, rest = text.partition(':')
    return key.strip(), rest.strip()


def _alias(text, anchors):
    """Return the node an alias names; YAML defines every anchor before its aliases."""
    return anchors[text[1:].strip()]


def _parse(lines, start, indent, anchors):
    """Parse the block-style subset .cnb.yml uses, from lines[start] at this indent; return (value, next).

    Anchors land in anchors as they are defined; aliases and `<<` merges resolve against it on the spot.
    """
    if lines[start][indent:].startswith('- '):
        items, i = [], start
        while i < len(lines) and _indent(lines[i]) == indent and lines[i][indent:].startswith('- '):
            item = lines[i][indent + 2:].strip()
            if item.startswith('&'):
                value, i = _parse(lines, i + 1, indent + 2, anchors)
                anchors[item[1:]] = value
                items.append(value)
                continue
            if item.startswith('*') or not MAPPING.match(item):
                items.append(_alias(item, anchors) if item.startswith('*') else _scalar(item))
                i += 1
                continue
            lines[i] = ' ' * (indent + 2) + item
            value, i = _parse(lines, i, indent + 2, anchors)
            items.append(value)
        return items, i
    result, merged, i = {}, {}, start
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith('#'):
            i += 1
            continue
        if _indent(line) < indent:
            break
        key, rest = _key(line.strip())
        anchor = None
        if rest.startswith('&'):
            anchor, _, rest = rest[1:].partition(' ')
            rest = rest.strip()
        i += 1
        if rest == '|':
            block = []
            while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > indent):
                block.append(lines[i])
                i += 1
            while block and not block[-1].strip():
                block.pop()
            depth = min(_indent(row) for row in block if row.strip())
            value = '\n'.join(row[depth:] for row in block) + '\n'
        elif rest:
            value = _alias(rest, anchors) if rest.startswith('*') else _scalar(rest)
        else:
            while i < len(lines) and not lines[i].strip():
                i += 1
            value, i = _parse(lines, i, _indent(lines[i]), anchors)
        if anchor:
            anchors[anchor] = value
        if key == '<<':
            merged.update(value)
        else:
            result[key] = value
    return {**merged, **result}, i


def _top(source, key):
    """Return the lines of one top-level key, the key line excluded."""
    lines = source.split('\n')
    start = next(i for i, line in enumerate(lines) if re.match(re.escape(key) + r':(\s|$)', line))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() and not lines[i].startswith(' ')),
               len(lines))
    return lines[start], lines[start + 1:end]


def text_main(source):
    """Read .cnb.yml's main block without yaml, resolving every anchor it aliases."""
    anchors = {}
    for header in re.findall(r'^(\.[\w-]+): &([\w-]+)$', source, re.M):
        _, body = _top(source, header[0])
        anchors[header[1]] = _parse(body, 0, 2, anchors)[0]
    _, body = _top(source, 'main')
    return _parse(body, 0, 2, anchors)[0]


def main_block():
    """Read the main block through yaml when this module has it, else through the text reader."""
    source = CNB.read_text(encoding='utf-8')
    if yaml is None:
        return text_main(source)
    return yaml.safe_load(source)['main']


def without_yaml():
    return patch.object(sys.modules[__name__], 'yaml', None)


def text_event(source, event):
    """Name the jobs of one event under `$` without yaml, following an alias to its anchor's `name:`."""
    _, body = _top(source, '$')
    start = body.index(f'  {event}:') + 1
    end = next((i for i in range(start, len(body)) if body[i].strip() and _indent(body[i]) <= 2), len(body))
    names = []
    for line in body[start:end]:
        item = line.strip()[2:]
        if _indent(line) != 4 or not line.strip().startswith('- '):
            continue
        if item.startswith('*'):
            item = re.search(r'^\.[\w-]+: &' + re.escape(item[1:]) + r'\n  (name: .+)$', source, re.M).group(1)
        names.append(_key(item)[1])
    return names


def event_jobs(event):
    source = CNB.read_text(encoding='utf-8')
    if yaml is None:
        return text_event(source, event)
    return [job['name'] for job in yaml.safe_load(source)['$'][event]]


class CnbPipelineTests(unittest.TestCase):
    """Every structural check runs through yaml when it is installed and again with yaml hidden."""

    def setUp(self):
        self.source = CNB.read_text(encoding='utf-8')

    def both(self, check):
        """Run one check in each reader this process has, so the two can never drift apart."""
        if yaml is not None:
            with self.subTest(reader='yaml'):
                check()
        with self.subTest(reader='text'), without_yaml():
            self.assertIsNone(sys.modules[__name__].yaml)
            check()

    def test_the_text_reader_matches_yaml(self):
        expected = text_main(self.source)
        self.assertEqual(['push', HOURLY], list(expected))
        if yaml is not None:
            self.assertEqual(yaml.safe_load(self.source)['main'], expected)

    def test_the_text_reader_places_an_alias_under_its_own_schedule(self):
        moved = '.other: &other\n  name: Other job\n' + self.source.replace(
            f'  "{HOURLY}":\n    - *mirror\n', f'  "{HOURLY}":\n    - *other\n')
        self.assertEqual(['Other job'], [job['name'] for job in text_main(moved)[HOURLY]])
        if yaml is not None:
            self.assertEqual(yaml.safe_load(moved)['main'], text_main(moved))

    def test_cnb_runs_no_ci(self):
        self.both(lambda: self.assertNotIn('pull_request', main_block()))
        self.assertNotRegex(self.source, r'(?m)^"?owner/')
        for text in ('Automation unit tests', 'Dependency vulnerability gate', 'ci_paths.py', 'endStages',
                     'cnbcool/sca-vulnerability', 'unittest discover', 'flutter test', 'cargo test', 'go test'):
            self.assertNotIn(text, self.source)
        if yaml is not None:
            self.assertEqual({'.mirror', 'main', '$'}, set(yaml.safe_load(self.source)))

    def test_every_alias_names_an_anchor_defined_before_it(self):
        anchors, aliases = [], []
        for line in self.source.splitlines():
            anchors += re.findall(r'(?:^|\s)&([\w-]+)$', line)
            for name in re.findall(r'^\s*-\s+\*([\w-]+)$', line):
                self.assertIn(name, anchors)
                aliases.append(name)
        self.assertEqual({'mirror'}, set(aliases))
        self.assertEqual({'mirror'}, set(anchors))

    def test_the_mirror_and_the_npc_events_stay(self):
        _, body = _top(self.source, '$')
        self.assertEqual(EVENTS, re.findall(r'^  (\S+):$', '\n'.join(body), re.M))
        self.both(lambda: self.assertEqual([MIRROR], [job['name'] for job in main_block()['push']]))
        for event in ('api_trigger', 'web_trigger'):
            self.both(lambda: self.assertEqual([MIRROR], event_jobs(event)))
        self.assertIn('script: python3 .cnb/mirror-release.py', self.source)

    def test_the_api_calls_that_still_start_a_build_find_their_pipeline(self):
        # Each of these names an event in a /build/start; removing one fails the run that reaches it.
        root = CNB.parent
        for script, event in (('.automation/control.py', 'api_trigger'), ('.automation/credentials.py', 'api_trigger'),
                              ('.github/scripts/npc_review.py', 'api_trigger_npc_review'),
                              ('.github/scripts/npc_review.py', 'api_trigger_npc_upstream')):
            self.assertIn(f"'{event}'", (root / script).read_text(encoding='utf-8'))
            self.assertIn(event, EVENTS)

    def test_the_controller_left_no_trigger_on_cnb(self):
        for text in ('wake.py', 'fallback.py', 'release_permission_probe.py', 'github-dispatch', 'crontab: */',
                     'issue.open', 'pull_request.target', 'pull_request.comment@npc', 'api_trigger_fallback',
                     'api_trigger_permissions', '开发助手', 'npc.Dockerfile', 'Paired review gate', '@npc', '助手'):
            self.assertNotIn(text, self.source)

    def test_no_npc_role_is_left_for_anyone_to_summon(self):
        root = CNB.parent
        self.assertEqual('workspace:', (root / '.cnb/settings.yml').read_text(encoding='utf-8').splitlines()[0])
        self.assertNotRegex((root / '.cnb/settings.yml').read_text(encoding='utf-8'), r'(?m)^npc:|助手')
        for path in (root / '.automation').glob('*.py'):
            if not path.name.startswith('test_'):
                self.assertNotIn('助手', path.read_text(encoding='utf-8'), path.name)
        self.assertNotIn('助手', (root / '.github/scripts/npc_review.py').read_text(encoding='utf-8'))

    def block(self, event):
        _, body = _top(self.source, '$')
        start = body.index(f'  {event}:')
        end = next(i for i in range(start + 1, len(body)) if body[i].strip() and _indent(body[i]) <= 2)
        return '\n'.join(body[start:end])

    def test_the_upstream_analysis_is_sandboxed_bounded_and_read_only(self):
        block = self.block('api_trigger_npc_upstream')
        self.assertIn('sandbox: true', block)
        self.assertRegex(block, r'maxTurns: \d+')
        self.assertIn('model: deepseek-v4.1-flash', block)
        self.assertEqual(['Fetch upstream from GitHub', 'NPC analysis', 'Review output'],
                         re.findall(r'^\s+- name: (.+)$', block, re.M)[1:])
        self.assertNotIn('imports:', block)
        self.assertNotIn('workMode', block)
        self.assertEqual(1, block.count('https://github.com/chen08209/FlClash.git'))
        for text in ('只读', '不回复 OK', '不写 @', 'FORK_PATCHES.md'):
            self.assertRegex(block, re.escape(text.replace('不写 @', '不写 @ 开头')))

    def test_the_upstream_analysis_checks_what_it_is_handed_before_using_it(self):
        script = self.block('api_trigger_npc_upstream').split('NPC analysis')[0]
        fetch = script.index('git fetch')
        for check in ('bad Issue number', 'bad tag', 'bad SHA'):
            self.assertLess(script.index(check), fetch)

    def test_the_npc_review_is_sandboxed_bounded_and_outside_every_gate(self):
        event = 'api_trigger_npc_review'
        _, body = _top(self.source, '$')
        start = body.index(f'  {event}:')
        end = next(i for i in range(start + 1, len(body)) if body[i].strip() and _indent(body[i]) <= 2)
        block = '\n'.join(body[start:end])
        self.assertIn('sandbox: true', block)
        self.assertRegex(block, r'maxTurns: \d+')
        self.assertIn('model: deepseek-v4.1-flash', block)
        self.assertEqual(['Fetch PR from GitHub', 'NPC review', 'Review output'],
                         re.findall(r'^\s+- name: (.+)$', block, re.M)[1:])
        self.assertNotIn('imports:', block)
        self.assertNotIn('workMode', block)
        self.assertEqual(1, block.count('https://github.com/initH271/FlClash-alpha.git'))
        self.assertIn('阻断', block)
        self.assertIn('具体输入', block)
        self.assertIn('预期输出', block)
        self.assertNotIn('PR_TITLE', block)
        if yaml is not None:
            self.assertEqual(['NPC PR review'], [job['name'] for job in yaml.safe_load(self.source)['$'][event]])

    def test_the_mirror_runs_hourly(self):
        def check():
            self.assertEqual([MIRROR], [job['name'] for job in main_block()[HOURLY]])
        self.both(check)


if __name__ == '__main__':
    unittest.main()
