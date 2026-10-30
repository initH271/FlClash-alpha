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
PIPELINE = 'Automation unit tests'
GATE = 'Paired review gate'
FILTER = "grep -Eq '^(\\.automation/|\\.cnb/|\\.cnb\\.yml|\\.github/|tool/)'"
DISCOVER = "python3 -m unittest discover -s .automation -p 'test_*.py'"
QUARTER = 'crontab: */15 * * * *'
HOURLY = 'crontab: 7 * * * *'


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


def _parse(lines, start, indent):
    """Parse the block-style subset .cnb.yml uses, from lines[start] at this indent; return (value, next)."""
    if lines[start][indent:].startswith('- '):
        items, i = [], start
        while i < len(lines) and _indent(lines[i]) == indent and lines[i][indent:].startswith('- '):
            item = lines[i][indent + 2:].strip()
            if not MAPPING.match(item) or item.startswith('*') or item.startswith('&'):
                if item.startswith('&'):
                    value, i = _parse(lines, i + 1, indent + 2)
                    items.append(value)
                    continue
                items.append({'*': item[1:]} if item.startswith('*') else _scalar(item))
                i += 1
                continue
            lines[i] = ' ' * (indent + 2) + item
            value, i = _parse(lines, i, indent + 2)
            items.append(value)
        return items, i
    result, i = {}, start
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith('#'):
            i += 1
            continue
        if _indent(line) < indent:
            break
        key, rest = _key(line.strip())
        i += 1
        if rest == '|':
            block = []
            while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > indent):
                block.append(lines[i])
                i += 1
            while block and not block[-1].strip():
                block.pop()
            depth = min(_indent(row) for row in block if row.strip())
            result[key] = '\n'.join(row[depth:] for row in block) + '\n'
        elif rest and not rest.startswith('&'):
            result[key] = _scalar(rest)
        else:
            while i < len(lines) and not lines[i].strip():
                i += 1
            result[key], i = _parse(lines, i, _indent(lines[i]))
    return result, i


def _resolve(value, anchors):
    if isinstance(value, dict):
        if set(value) == {'*'}:
            return anchors[value['*']]
        return {key: _resolve(item, anchors) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, anchors) for item in value]
    return value


def _top(source, key):
    """Return the lines of one top-level key, the key line excluded."""
    lines = source.split('\n')
    start = next(i for i, line in enumerate(lines) if re.match(re.escape(key) + r':(\s|$)', line))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() and not lines[i].startswith(' ')),
               len(lines))
    return lines[start], lines[start + 1:end]


def text_main(source):
    """Read .cnb.yml's main block without yaml, resolving the top-level anchors it aliases."""
    anchors = {}
    for header in re.findall(r'^(\.[\w-]+): &([\w-]+)$', source, re.M):
        _, body = _top(source, header[0])
        anchors[header[1]] = _parse(body, 0, 2)[0]
    _, body = _top(source, 'main')
    return _resolve(_parse(body, 0, 2)[0], anchors)


def main_block():
    """Read the main block through yaml when this module has it, else through the text reader."""
    source = CNB.read_text(encoding='utf-8')
    if yaml is None:
        return text_main(source)
    return yaml.safe_load(source)['main']


def pipelines():
    return main_block()['pull_request']


def without_yaml():
    return patch.object(sys.modules[__name__], 'yaml', None)


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
        self.assertEqual(['Dependency vulnerability gate', PIPELINE],
                         [entry['name'] for entry in expected['pull_request']][:2])
        if yaml is not None:
            self.assertEqual(yaml.safe_load(self.source)['main'], expected)

    def test_the_text_reader_places_an_alias_under_its_own_schedule(self):
        moved = self.source.replace(f'  "{HOURLY}":\n    - *mirror\n', f'  "{HOURLY}":\n    - *controller-wake\n')
        self.assertEqual(['Wake task controller'], [job['name'] for job in text_main(moved)[HOURLY]])
        if yaml is not None:
            self.assertEqual(yaml.safe_load(moved)['main'], text_main(moved))

    def test_pull_request_declares_automation_unit_tests(self):
        self.both(lambda: self.assertIn(PIPELINE, [entry.get('name') for entry in pipelines()]))

    def test_pull_request_pipelines_settle_in_a_final_stage(self):
        def check():
            entries = pipelines()
            self.assertEqual(5, len(entries))
            for entry in entries:
                self.assertEqual(1, len(entry.get('endStages', [])), entry['name'])
        self.both(check)

    def test_pipeline_skips_unrelated_pull_requests(self):
        self.assertIn(FILTER, self.source)
        self.assertIn("echo 'Skipped: no automation changes'", self.source)

    def test_pipeline_runs_every_automation_test(self):
        self.assertIn(DISCOVER, self.source)

    def test_pipeline_precedes_go_regression_tests(self):
        def check():
            names = [entry['name'] for entry in pipelines()]
            self.assertLess(names.index(PIPELINE), names.index('Go dependency regression tests'))
        self.both(check)

    def test_pipeline_definition_is_bounded(self):
        def check():
            entry = next(item for item in pipelines() if item.get('name') == PIPELINE)
            self.assertEqual({'cpus': 1}, entry['runner'])
            self.assertEqual('python:3.12', entry['docker']['image'])
            self.assertEqual(1, len(entry['stages']))
            stage = entry['stages'][0]
            self.assertEqual('10m', stage['timeout'])
            self.assertIn(FILTER, stage['script'])
            self.assertIn(DISCOVER, stage['script'])
        self.both(check)

    def test_ci_pipelines_are_exactly_the_pull_request_jobs_and_never_wait_for_the_gate(self):
        import reviews
        self.both(lambda: self.assertEqual([entry['name'] for entry in pipelines()], list(reviews.CI_PIPELINES)))
        self.assertNotIn(GATE, reviews.CI_PIPELINES)
        # The gate is a pull_request.target job: it sits in that block, before the next event key.
        self.assertRegex(self.source, r'\n  pull_request\.target:\n(    .*\n|      .*\n)*?    - name: ' + GATE + r'\n')
        pull = {'number': '12', 'base': {'sha': 'a' * 40},
                'head': {'sha': 'b' * 40, 'ref': 'refs/heads/automation/req-9'}}
        five = [{'context': f'cnb/pipeline-{i}({name})', 'state': 'success', 'created_at': '2026-10-30T00:00:00Z'}
                for i, name in enumerate(reviews.CI_PIPELINES)]
        # The gate starts with the PR and only passes after the review it is waiting for, so it is pending or absent.
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

    def test_every_pipeline_wakes_the_controller_when_it_ends(self):
        job = "python3 .automation/wake.py ci-done '{}'"

        def check():
            for entry in pipelines():
                (stage,) = entry['endStages']
                self.assertEqual('python:3.12-slim', stage['image'])
                self.assertEqual('2m', stage['timeout'])
                self.assertEqual(job.format(entry['name']), stage['script'])
        self.both(check)

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
            self.assertNotIn('Mirror signed GitHub release to CNB', [job['name'] for job in schedules[QUARTER]])
            self.assertEqual(['Mirror signed GitHub release to CNB'], [job['name'] for job in schedules[HOURLY]])
        self.both(check)


if __name__ == '__main__':
    unittest.main()
