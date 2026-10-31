import importlib.util
import os
import pathlib
import re
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/npc-review.yml').read_text(encoding='utf-8')
CI = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
spec = importlib.util.spec_from_file_location('npc_review', ROOT / '.github/scripts/npc_review.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
HEAD, BASE = 'b' * 40, 'a' * 40
ENV = {'PR_NUMBER': '12', 'PR_BASE': BASE, 'PR_HEAD': HEAD, 'CNB_AUTOMATION_TOKEN': 't', 'GH_TOKEN': 'g',
       'GITHUB_REPOSITORY': 'o/r'}


class TextTests(unittest.TestCase):
    def test_output_cannot_notify_anyone_or_spoof_the_marker(self):
        for raw, reached in (('@owner', '@owner'), ('see #12', '#12'), ('&#64;owner', '&#64;'), ('&commat;owner', '&commat;'),
                             ('<!-- flclash-npc-review -->', '<!--')):
            with self.subTest(raw=raw):
                self.assertNotIn(reached, bridge.neutralize(raw))
        self.assertEqual(bridge.MARKER, bridge.render('<!-- flclash-npc-review --> @x', HEAD).split('\n')[0])
        self.assertEqual(1, bridge.render('<!-- flclash-npc-review -->', HEAD).count(bridge.MARKER))

    def test_output_is_truncated_and_empty_output_says_so(self):
        self.assertLess(len(bridge.render('x' * 100000, HEAD)), bridge.MAX_REVIEW_CHARS + 200)
        for empty in ('', '  \n', None):
            self.assertIn(bridge.NO_REVIEW, bridge.render(empty, HEAD))


class ResultTests(unittest.TestCase):
    STATUS = {'status': 'success', 'pipelinesStatus': {'p-001': {'id': 'p-001', 'stages': [
        {'id': 'stage-1', 'name': 'NPC review', 'status': 'success'},
        {'id': 'stage-2', 'name': bridge.OUTPUT_STAGE, 'status': 'success'},
        {'id': 'beforeEnd', 'name': 'BeforeEnd', 'status': 'success'}]}}}

    def test_the_stage_is_found_by_name_not_by_position(self):
        self.assertEqual(('p-001', 'stage-2'), bridge.output_stage(self.STATUS))

    def test_a_skipped_output_stage_or_no_pipeline_gives_nothing(self):
        skipped = {'pipelinesStatus': {'p': {'stages': [{'id': 's', 'name': bridge.OUTPUT_STAGE, 'status': 'skipped'}]}}}
        for status in (skipped, {'status': 'error'}, {'pipelinesStatus': None}):
            self.assertIsNone(bridge.output_stage(status))

    def test_the_report_comes_from_the_real_log_shape(self):
        log = ['\x1b[32mRunner[1][docker] 2026 $\x1b[0m', '\x1b[37mecho NPC_REVIEW_BEGIN\x1b[39m',
               '\x1b[37mecho NPC_REVIEW_END\x1b[39m', 'NPC_REVIEW_BEGIN', '**结论**：无', '', 'NPC_REVIEW_END', 'NPC_REVIEW_END',
               'tail', 'NPC_REVIEW_END', '', '\x1b[37mFinished, code: 0\x1b[0m']
        self.assertEqual('**结论**：无\n\nNPC_REVIEW_END\nNPC_REVIEW_END\ntail', bridge.extract_report(log))

    def test_an_aborted_review_exports_nothing(self):
        # maxTurns ends the NPC with an empty export while the output stage still succeeds (cnb-d43-1k6854mi0).
        self.assertEqual('', bridge.extract_report(['NPC_REVIEW_BEGIN', '', 'NPC_REVIEW_END']))
        self.assertEqual('', bridge.extract_report(None))


class CommentTests(unittest.TestCase):
    OURS = {'id': 7, 'user': {'login': bridge.BOT}, 'body': bridge.MARKER + '\nold'}
    PLANTED = {'id': 8, 'user': {'login': 'someone'}, 'body': bridge.MARKER + '\nfake'}

    def test_only_the_bots_own_comment_is_ours(self):
        self.assertIsNone(bridge.existing_comment([self.PLANTED]))
        self.assertEqual(7, bridge.existing_comment([self.PLANTED, self.OURS])['id'])

    def test_a_new_head_updates_and_no_review_stays_silent_without_a_comment(self):
        self.assertEqual('PATCH', bridge.comment_action(self.OURS, 'r'))
        self.assertEqual('PATCH', bridge.comment_action(self.OURS, ''))
        self.assertEqual('POST', bridge.comment_action(None, 'r'))
        self.assertIsNone(bridge.comment_action(None, ' '))


class RunTests(unittest.TestCase):
    def drive(self, cnb, comments=()):
        writes = []

        def github(path, method='GET', data=None):
            if method == 'GET':
                return list(comments) if path.endswith('page=1') else []
            writes.append((method, path, data['body']))
            return {}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {**ENV, 'RUNNER_TEMP': temp}), \
                patch.object(bridge, 'cnb', side_effect=cnb), patch.object(bridge, 'github', side_effect=github), \
                patch.object(bridge.time, 'sleep'), patch('builtins.print'):
            self.assertEqual(0, bridge.main(['npc_review.py', 'run']))
        return writes

    def test_a_refused_start_writes_nothing_and_stays_green(self):
        def cnb(path, method='GET', data=None):
            raise OSError('400 event missing')
        self.assertEqual([], self.drive(cnb))

    def test_a_failure_on_a_new_head_replaces_the_stale_advice(self):
        def cnb(path, method='GET', data=None):
            raise OSError('down')
        writes = self.drive(cnb, [CommentTests.OURS])
        self.assertEqual([('PATCH', '/issues/comments/7')], [w[:2] for w in writes])
        self.assertIn(bridge.NO_REVIEW, writes[0][2])

    def test_the_request_carries_only_the_validated_identity_and_the_npc_field(self):
        seen = []

        def cnb(path, method='GET', data=None):
            if path == '/build/start':
                seen.append(data)
                return {'sn': 'cnb-1'}
            if path.startswith('/build/status/'):
                return ResultTests.STATUS
            return {'content': ['NPC_REVIEW_BEGIN', '@a 结论', 'NPC_REVIEW_END']}
        writes = self.drive(cnb)
        self.assertEqual({'name': 'CodeBuddy'}, seen[0]['npc'])
        self.assertEqual({'PR_NUMBER': '12', 'PR_BASE': BASE, 'PR_HEAD': HEAD}, seen[0]['env'])
        self.assertEqual([('POST', '/issues/12/comments')], [w[:2] for w in writes])
        self.assertNotIn('@a', writes[0][2])

    def test_a_bad_sha_never_reaches_cnb(self):
        with patch.dict(os.environ, {**ENV, 'PR_HEAD': '$(id)'}), patch.object(bridge, 'cnb') as cnb, patch('builtins.print'):
            self.assertEqual(0, bridge.main(['npc_review.py', 'run']))
        cnb.assert_not_called()

    def test_the_deadline_stops_the_build(self):
        ticks = iter(range(0, 10 ** 6, bridge.DEADLINE_SECONDS // 2))
        calls = []

        def cnb(path, method='GET', data=None):
            calls.append((method, path))
            return {'status': 'pending'}
        with patch.object(bridge, 'cnb', side_effect=cnb):
            self.assertIsNone(bridge.wait_for('cnb-1', clock=lambda: next(ticks), sleep=lambda s: None))
        self.assertEqual(('POST', '/build/stop/cnb-1'), calls[-1])

    def test_a_cancelled_run_stops_its_build(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'RUNNER_TEMP': temp}), \
                patch.object(bridge, 'cnb') as cnb:
            bridge.main(['npc_review.py', 'stop'])
            cnb.assert_not_called()
            bridge.sn_file().write_text('cnb-9')
            bridge.main(['npc_review.py', 'stop'])
        cnb.assert_called_once_with('/build/stop/cnb-9', 'POST')


class WorkflowTests(unittest.TestCase):
    def test_it_stays_out_of_the_gate(self):
        self.assertNotIn('npc', CI.lower())
        self.assertNotRegex(WORKFLOW, r'(?m)^\s+name: ci-ok')

    def test_triggers_and_permissions_are_minimal(self):
        self.assertIn('types: [opened, synchronize, ready_for_review, reopened]', WORKFLOW)
        self.assertNotIn('pull_request_target', WORKFLOW)
        self.assertIn('permissions:\n  contents: read\n  pull-requests: write\nconcurrency:', WORKFLOW)
        self.assertIn('cancel-in-progress: true', WORKFLOW)
        self.assertIn('runs-on: ubuntu-24.04', WORKFLOW)

    def test_forks_and_drafts_are_skipped(self):
        self.assertIn('github.event.pull_request.draft == false', WORKFLOW)
        self.assertIn('github.event.pull_request.head.repo.full_name == github.repository', WORKFLOW)

    def test_pr_code_is_not_run_and_no_pr_text_reaches_a_shell(self):
        self.assertIn('ref: ${{ github.event.pull_request.base.sha }}', WORKFLOW)
        self.assertIn('persist-credentials: false', WORKFLOW)
        self.assertFalse(re.search(r'\$\{\{.*(title|body|head\.ref|label)', WORKFLOW))
        for command in re.findall(r'^\s+run: (.*)$', WORKFLOW, re.M):
            self.assertNotIn('${{', command)

    def test_no_step_can_fail_the_job(self):
        steps = re.split(r'^      - ', WORKFLOW.split('steps:\n')[1], flags=re.M)[1:]
        self.assertEqual(3, len(steps))
        for step in steps:
            self.assertIn('continue-on-error: true', step)

    def test_a_cancelled_run_cleans_up(self):
        self.assertIn('if: cancelled()', WORKFLOW)


if __name__ == '__main__':
    unittest.main()
