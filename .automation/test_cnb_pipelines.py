import pathlib
import unittest

try:
    import yaml
except ImportError:
    yaml = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
CNB = ROOT / '.cnb.yml'
PIPELINE = 'Automation unit tests'
FILTER = "grep -Eq '^(\\.automation/|\\.cnb/|\\.cnb\\.yml|\\.github/|tool/)'"
DISCOVER = "python3 -m unittest discover -s .automation -p 'test_*.py'"


def pipelines():
    if yaml is None:
        return None
    return yaml.safe_load(CNB.read_text(encoding='utf-8'))['main']['pull_request']


class CnbPipelineTests(unittest.TestCase):
    def setUp(self):
        self.source = CNB.read_text(encoding='utf-8')

    def test_pull_request_declares_automation_unit_tests(self):
        entries = pipelines()
        if entries is None:
            self.assertIn(f'    - name: {PIPELINE}\n', self.source)
            return
        self.assertIn(PIPELINE, [entry.get('name') for entry in entries])

    def test_pipeline_skips_unrelated_pull_requests(self):
        self.assertIn(FILTER, self.source)
        self.assertIn("echo 'Skipped: no automation changes'", self.source)

    def test_pipeline_runs_every_automation_test(self):
        self.assertIn(DISCOVER, self.source)

    def test_pipeline_precedes_go_regression_tests(self):
        self.assertLess(self.source.index(f'- name: {PIPELINE}'),
                        self.source.index('- name: Go dependency regression tests'))

    def test_pipeline_definition_is_bounded(self):
        entries = pipelines()
        if entries is None:
            return
        entry = next(item for item in entries if item.get('name') == PIPELINE)
        self.assertEqual({'cpus': 1}, entry['runner'])
        self.assertEqual('python:3.12', entry['docker']['image'])
        self.assertTrue(entry['docker']['image'].startswith('python:3'))
        self.assertEqual(1, len(entry['stages']))
        stage = entry['stages'][0]
        self.assertEqual('10m', stage['timeout'])
        self.assertIn(FILTER, stage['script'])
        self.assertIn(DISCOVER, stage['script'])


if __name__ == '__main__':
    unittest.main()
