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
GATE = 'Paired review gate'
QUARTER = 'crontab: */15 * * * *'
HOURLY = 'crontab: 7 * * * *'
MIRROR = 'Mirror signed GitHub release to CNB'
# CI runs on GitHub. These stay until the controller is removed, except the mirror and the NPC review, which stay for good.
EVENTS = ['issue.open', 'issue.comment', 'pull_request.target', 'api_trigger', 'web_trigger', 'api_trigger_fallback',
          'api_trigger_permissions', 'api_trigger_npc_review', 'issue.comment@npc', 'pull_request.comment@npc', 'vscode']


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
        self.assertEqual(['push', QUARTER, HOURLY], list(expected))
        if yaml is not None:
            self.assertEqual(yaml.safe_load(self.source)['main'], expected)

    def test_the_text_reader_places_an_alias_under_its_own_schedule(self):
        moved = self.source.replace(f'  "{HOURLY}":\n    - *mirror\n', f'  "{HOURLY}":\n    - *controller-wake\n')
        self.assertEqual(['Wake task controller'], [job['name'] for job in text_main(moved)[HOURLY]])
        if yaml is not None:
            self.assertEqual(yaml.safe_load(moved)['main'], text_main(moved))

    def test_cnb_runs_no_ci(self):
        self.both(lambda: self.assertNotIn('pull_request', main_block()))
        self.assertNotRegex(self.source, r'(?m)^"?owner/')
        import reviews
        for text in (*reviews.CI_PIPELINES, 'ci_paths.py', 'wake.py ci-done', 'endStages', 'cnbcool/sca-vulnerability',
                     'unittest discover', 'flutter test', 'cargo test', 'go test'):
            self.assertNotIn(text, self.source)
        if yaml is not None:
            self.assertEqual({'.mirror', '.controller-wake', 'main', '$', '开发助手'}, set(yaml.safe_load(self.source)))

    def test_every_alias_names_an_anchor_defined_before_it(self):
        anchors, aliases = [], []
        for line in self.source.splitlines():
            anchors += re.findall(r'(?:^|\s)&([\w-]+)$', line)
            for name in re.findall(r'^\s*-\s+\*([\w-]+)$', line):
                self.assertIn(name, anchors)
                aliases.append(name)
        self.assertEqual({'mirror', 'controller-wake', 'reviewer-npc'}, set(aliases))

    def test_the_events_the_controller_and_the_mirror_use_stay(self):
        _, body = _top(self.source, '$')
        self.assertEqual(EVENTS, re.findall(r'^  (\S+):$', '\n'.join(body), re.M))
        self.both(lambda: self.assertEqual([MIRROR], [job['name'] for job in main_block()['push']]))
        for event in ('api_trigger', 'web_trigger'):
            self.both(lambda: self.assertEqual([MIRROR], event_jobs(event)))

    def test_controller_paths_that_still_run_on_cnb_find_their_pipeline(self):
        # Each of these names an event in a /build/start or a script path; removing one fails the run that reaches it.
        root = CNB.parent
        fallback = (root / '.automation/fallback.py').read_text(encoding='utf-8')
        credentials = (root / '.automation/credentials.py').read_text(encoding='utf-8')
        control = (root / '.automation/control.py').read_text(encoding='utf-8')
        review = (root / '.github/scripts/npc_review.py').read_text(encoding='utf-8')
        for source, event in ((fallback, 'api_trigger_fallback'), (credentials, 'api_trigger_permissions'),
                              (control, 'api_trigger'), (review, 'api_trigger_npc_review')):
            self.assertIn(f"'{event}'", source)
            self.assertIn(event, EVENTS)
        self.assertIn('python3 .automation/fallback.py produce', self.source)
        self.assertIn('python3 .automation/release_permission_probe.py', self.source)

    def test_a_cnb_pull_without_ci_waits_and_is_never_called_failed(self):
        # What a CNB requirement or security pull sees until the controller is removed: no CI row ever arrives.
        import requirements
        import reviews
        import security_finish
        wake = [{'context': 'cnb/pipeline-1(Wake task controller)', 'state': 'success'}]
        for rows in ([], wake):
            checks = {'statuses': rows}
            self.assertEqual('pending', reviews.ci_state(checks))
            with patch.object(requirements.control, 'api', return_value=checks):
                self.assertEqual((False, False), requirements.check_state('12'))
            with patch.object(security_finish, 'api', return_value=checks):
                self.assertFalse(security_finish.passed_checks('12'))

    def test_the_ci_list_still_reads_old_rows_and_ignores_the_gate(self):
        import reviews
        self.assertNotIn(GATE, reviews.CI_PIPELINES)
        pull = {'number': '12', 'base': {'sha': 'a' * 40},
                'head': {'sha': 'b' * 40, 'ref': 'refs/heads/automation/req-9'}}
        five = [{'context': f'cnb/pipeline-{i}({name})', 'state': 'success', 'created_at': '2026-10-30T00:00:00Z'}
                for i, name in enumerate(reviews.CI_PIPELINES)]
        # A head pushed before the gate pipeline was removed may still carry its row; it never holds CI.
        for gate in ([], [{'context': f'cnb/pipeline-9({GATE})', 'state': 'pending',
                           'created_at': '2026-10-30T00:00:00Z'}]):
            checks = {'statuses': five + gate}
            self.assertEqual('success', reviews.ci_state(checks))

            def api(url, method='GET', data=None, missing=False, timeout=60):
                self.assertTrue(url.endswith('/pulls/12/commit-statuses'), url)
                return checks
            with (patch.object(reviews, 'api', side_effect=api),
                  patch.object(reviews, 'pages', side_effect=lambda url, page_key='page', size_key='page_size': iter([]))):
                self.assertEqual((False, False), reviews.ci_hold(pull))

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

    def test_the_paired_review_gate_pipeline_is_gone(self):
        # 2-1c: the 32-minute polling job only produced timeouts; the review verdict decides on its own.
        self.assertNotIn(GATE, self.source)
        self.assertNotIn('cnb-gate', self.source)
        target = 'pull_request.target'
        if yaml is not None:
            self.assertEqual([job['name'] for job in yaml.safe_load(self.source)['$'][target]],
                             text_event(self.source, target))
        self.both(lambda: self.assertEqual(['Wake task controller'], event_jobs(target)))

    def test_the_sleeping_waker_and_the_five_minute_schedule_are_gone(self):
        self.assertNotIn('Wake controller after checks', self.source)
        self.assertNotIn('crontab: */5', self.source)
        self.assertNotIn('wake.py settled', self.source)

    def test_the_quarter_hour_schedule_watches_stalls_and_wakes_the_controller(self):
        def check():
            jobs = main_block()[QUARTER]
            self.assertIn('python3 .automation/wake.py watchdog', jobs[0]['stages'][0]['script'])
            self.assertEqual('3m', jobs[0]['stages'][0]['timeout'])
            self.assertIn('github-dispatch.yml', jobs[1]['stages'][0]['imports'])
            self.assertEqual('python3 .automation/wake.py', jobs[1]['stages'][0]['script'])
            self.assertEqual('2m', jobs[1]['stages'][0]['timeout'])
        self.both(check)

    def test_the_mirror_runs_hourly(self):
        def check():
            schedules = main_block()
            self.assertNotIn(MIRROR, [job['name'] for job in schedules[QUARTER]])
            self.assertEqual([MIRROR], [job['name'] for job in schedules[HOURLY]])
        self.both(check)


if __name__ == '__main__':
    unittest.main()
