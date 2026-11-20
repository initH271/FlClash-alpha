import unittest
from unittest.mock import patch

import control
import scheduler


class VersionTests(unittest.TestCase):
    def test_prereleases_not_stable_versions(self):
        self.assertIsNone(control.version('v0.8.99-pre.1'))
        self.assertGreater(control.version('v0.8.100'), control.version('v0.8.99'))


class RecoveryTests(unittest.TestCase):
    def test_test_failure_never_reuses_even_with_artifact(self):
        steps = [{'name': 'Analyze and test', 'conclusion': 'failure'}]
        self.assertFalse(scheduler.can_reuse(steps, True))

    def test_existing_artifact_reused_after_publication_failure(self):
        steps = [{'name': 'Publish GitHub release', 'conclusion': 'failure'}]
        self.assertTrue(scheduler.can_reuse(steps, True))

    def test_without_an_artifact_nothing_is_reused(self):
        for name in ('Build ARM64 APK', 'Run actions/setup-go@v5'):
            self.assertFalse(scheduler.can_reuse([{'name': name, 'conclusion': 'failure'}], False))

    def test_running_primary_never_dispatches(self):
        for status in ('in_progress', 'queued'):
            run = {'id': 10, 'display_title': 'Android ' + 'a' * 40, 'status': status, 'conclusion': None}
            with patch.object(scheduler, 'api', return_value={'workflow_runs': [run]}), patch.object(scheduler, 'dispatch') as dispatch:
                scheduler.schedule()
            dispatch.assert_not_called()

    def test_recovery_run_never_recursively_retries(self):
        run = {'id': 10, 'display_title': 'Android ' + 'a' * 40 + ' recovery', 'status': 'completed', 'conclusion': 'failure'}
        with patch.object(scheduler, 'api', return_value={'workflow_runs': [run]}), patch.object(scheduler, 'dispatch') as dispatch, patch.object(scheduler, 'notify_once') as notify:
            scheduler.schedule()
        dispatch.assert_not_called()
        notify.assert_called_once()

    def test_manual_cancellation_is_not_restarted(self):
        run = {'id': 10, 'display_title': 'Android ' + 'a' * 40, 'status': 'completed', 'conclusion': 'cancelled'}
        with patch.object(scheduler, 'api', return_value={'workflow_runs': [run]}), patch.object(scheduler, 'dispatch') as dispatch:
            scheduler.schedule()
        dispatch.assert_not_called()

    run_url = 'https://github.com/x/y/actions/runs/10'

    def schedule(self, steps, artifacts, conclusion='failure', later=(), tracked=()):
        run = {'id': 10, 'display_title': 'Android ' + 'a' * 40, 'status': 'completed', 'conclusion': conclusion,
               'html_url': self.run_url}
        posts = []

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if method == 'POST':
                posts.append((url, data))
                return {}
            if 'workflows/build.yaml/runs' in url:
                return {'workflow_runs': [*later, run]}
            if '/git/ref/heads/automation/recovery-' in url:
                return None
            if url.endswith('/artifacts'):
                return {'artifacts': artifacts}
            if url.endswith('/jobs'):
                return {'jobs': [{'steps': steps}]}
            self.fail('Unexpected API call: ' + url)

        with patch.object(scheduler, 'api', api), patch.object(control, 'api', api), \
                patch.object(scheduler, 'bot_issues', return_value=list(tracked)):
            scheduler.schedule()
        return posts

    def test_a_publication_failure_dispatches_one_reuse_of_the_exact_source(self):
        posts = self.schedule([{'name': 'Publish GitHub release', 'conclusion': 'failure'}],
                              [{'name': 'FlClash-arm64-log-history', 'expired': False}])
        self.assertEqual(2, len(posts))
        self.assertTrue(posts[0][0].endswith('/git/refs'))
        self.assertTrue(posts[1][0].endswith('/build.yaml/dispatches'))
        self.assertEqual({'source_ref': 'a' * 40, 'reuse_run': '10'}, posts[1][1]['inputs'])

    def test_a_setup_failure_only_notifies_and_starts_no_build(self):
        posts = self.schedule([{'name': 'Run actions/setup-go@v5', 'conclusion': 'failure'}], [])
        self.assertEqual(1, len(posts))
        self.assertEqual(f'{control.GH}/issues', posts[0][0])
        self.assertIn('[构建待处理] GitHub #10', posts[0][1]['title'])
        self.assertEqual([control.OWNER], posts[0][1]['assignees'])
        self.assertNotIn('@', posts[0][1]['body'])
        self.assertIn(self.run_url, posts[0][1]['body'])

    def test_one_run_opens_one_issue(self):
        posts = self.schedule([{'name': 'Run actions/setup-go@v5', 'conclusion': 'failure'}], [],
                              tracked=[{'title': '[构建待处理] GitHub #10'}])
        self.assertEqual([], posts)

    def test_a_later_green_build_of_main_leaves_nothing_to_do(self):
        later = [{'id': 11, 'display_title': 'Android ' + 'b' * 40, 'status': 'completed', 'conclusion': 'success'}]
        self.assertEqual([], self.schedule([{'name': 'Publish GitHub release', 'conclusion': 'failure'}],
                                           [{'name': 'FlClash-arm64-log-history', 'expired': False}], later=later))
        self.assertEqual([], self.schedule([{'name': 'Run actions/setup-go@v5', 'conclusion': 'failure'}], [], later=later))

    def test_a_later_build_still_running_or_failed_does_not_hide_a_failure(self):
        for status, conclusion in (('in_progress', None), ('completed', 'failure')):
            later = [{'id': 11, 'display_title': 'Android ' + 'b' * 40, 'status': status, 'conclusion': conclusion,
                      'html_url': self.run_url}]
            titles = [post[1]['title'] for post in self.schedule([{'name': 'Run actions/setup-go@v5', 'conclusion': 'failure'}], [], later=later)]
            self.assertIn('[构建待处理] GitHub #10', titles)

    def test_a_startup_failure_stays_quiet(self):
        self.assertEqual([], self.schedule([], [], 'startup_failure'))


class ValidateSourceTests(unittest.TestCase):
    def test_the_current_main_is_accepted_after_only_reading_its_ref(self):
        sha = 'a' * 40
        with patch.object(control, 'git', return_value=sha), \
                patch.object(control, 'api', return_value={'object': {'sha': sha}}) as api:
            control.validate_source()
        self.assertTrue(all(call.args[0].endswith('/git/ref/heads/main') for call in api.call_args_list))
        self.assertTrue(all(len(call.args) == 1 for call in api.call_args_list))

    def test_a_source_that_is_not_main_is_refused(self):
        with patch.object(control, 'git', return_value='b' * 40), \
                patch.object(control, 'api', return_value={'object': {'sha': 'a' * 40}}):
            with self.assertRaisesRegex(ValueError, 'not the current main'):
                control.validate_source()


if __name__ == '__main__':
    unittest.main()
