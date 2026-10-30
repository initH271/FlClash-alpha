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

    def test_pull_request_pipelines_settle_in_a_final_stage(self):
        entries = pipelines()
        if entries is None:
            return
        for entry in entries:
            # The paired review gate is a pull_request.target job and has no end stage of its own.
            self.assertEqual(0 if entry['name'] == 'Paired review gate' else 1, len(entry.get('endStages', [])))

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


    def schedules(self):
        if yaml is None:
            return None
        return yaml.safe_load(CNB.read_text(encoding='utf-8'))['main']

    def test_ci_pipelines_match_the_pull_request_jobs(self):
        from reviews import CI_PIPELINES
        entries = pipelines()
        if entries is None:
            for name in CI_PIPELINES:
                self.assertIn(f'    - name: {name}\n', self.source)
            return
        # The paired review gate lives under pull_request.target, so CI_PIPELINES names it last.
        self.assertEqual(list(CI_PIPELINES[:-1]), [entry['name'] for entry in entries])
        self.assertEqual('Paired review gate', CI_PIPELINES[-1])

    def test_every_pipeline_wakes_the_controller_when_it_ends(self):
        from reviews import CI_PIPELINES
        job = "python3 .automation/wake.py ci-done '{}'"
        entries = pipelines()
        # The paired review gate is a pull_request.target job, so it has no end stage of its own.
        for name in CI_PIPELINES[:-1]:
            self.assertIn(job.format(name), self.source)
            if entries is None:
                continue
            entry = next(item for item in entries if item.get('name') == name)
            (stage,) = entry['endStages']
            self.assertEqual('python:3.12-slim', stage['image'])
            self.assertEqual('2m', stage['timeout'])
            self.assertEqual(job.format(name), stage['script'])

    def test_the_sleeping_waker_and_the_five_minute_schedule_are_gone(self):
        self.assertNotIn('Wake controller after checks', self.source)
        self.assertNotIn('crontab: */5', self.source)
        self.assertNotIn('wake.py settled', self.source)

    def test_the_quarter_hour_schedule_watches_stalls_and_wakes_the_controller(self):
        entries = self.schedules()
        if entries is None:
            self.assertIn('"crontab: */15 * * * *":', self.source)
            self.assertRegex(self.source, r'(?s)"crontab: \*/15 \* \* \* \*":.*python3 \.automation/wake\.py watchdog')
            self.assertRegex(self.source, r'(?s)"crontab: \*/15 \* \* \* \*":.*github-dispatch\.yml')
            self.assertRegex(self.source, r'(?s)"crontab: \*/15 \* \* \* \*":.*python3 \.automation/wake\.py\n')
            return
        jobs = entries['crontab: */15 * * * *']
        self.assertIn('python3 .automation/wake.py watchdog', jobs[0]['stages'][0]['script'])
        self.assertEqual('3m', jobs[0]['stages'][0]['timeout'])
        self.assertIn('github-dispatch.yml', jobs[1]['stages'][0]['imports'])
        self.assertEqual('python3 .automation/wake.py', jobs[1]['stages'][0]['script'])
        self.assertEqual('2m', jobs[1]['stages'][0]['timeout'])

    def test_the_mirror_runs_hourly(self):
        entries = self.schedules()
        if entries is None:
            self.assertIn('"crontab: 7 * * * *":', self.source)
            self.assertIn('    - *mirror\n', self.source)
            return
        self.assertNotIn('*mirror', entries['crontab: */15 * * * *'])
        self.assertEqual(['Mirror signed GitHub release to CNB'],
                         [job['name'] for job in entries['crontab: 7 * * * *']])

if __name__ == '__main__':
    unittest.main()
