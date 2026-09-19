import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import control
import scheduler


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.key = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'unit-test-key'})
        self.key.start()
        self.addCleanup(self.key.stop)

    def test_valid_signed_issue_roundtrip(self):
        payload = {'tag': 'v0.8.98', 'sha': 'a' * 40, 'upstream': control.POLICY['upstream']}
        self.assertEqual(payload, control.parse_request(control.marker(payload)))

    def test_modified_commit_rejected(self):
        signed = control.sign({'sha': 'a' * 40})
        signed['payload']['sha'] = 'b' * 40
        with self.assertRaises(ValueError):
            control.verify(signed)

    def test_unrelated_or_missing_marker_not_approval(self):
        self.assertIsNone(control.parse_request('Please update everything'))

    def test_only_exact_owner_ok_approves(self):
        owner = {'username': 'Aharon', 'is_npc': False}
        self.assertTrue(control.approved({'author': owner, 'body': ' OK '}, 'v0.8.98'))
        self.assertTrue(control.approved({'author': owner, 'body': 'ok v0.8.98'}, 'v0.8.98'))
        for body in ('looks OK', 'OK v0.8.99', 'OK\nrun anything'):
            self.assertFalse(control.approved({'author': owner, 'body': body}, 'v0.8.98'))
        self.assertFalse(control.approved({'author': {'username': 'visitor', 'is_npc': False}, 'body': 'OK'}, 'v0.8.98'))
        self.assertFalse(control.approved({'author': {'username': 'Aharon', 'is_npc': True}, 'body': 'OK'}, 'v0.8.98'))
        self.assertFalse(control.approved({'author': {'username': 'Aharon'}, 'body': 'OK'}, 'v0.8.98'))

    def test_prereleases_not_stable_versions(self):
        self.assertIsNone(control.version('v0.8.99-pre.1'))
        self.assertGreater(control.version('v0.8.100'), control.version('v0.8.99'))


class RecoveryTests(unittest.TestCase):
    def test_test_failure_never_fails_over_even_with_artifact(self):
        steps = [{'name': 'Analyze and test', 'conclusion': 'failure'}]
        self.assertIsNone(scheduler.recovery_kind(steps, 'failure', True))

    def test_existing_artifact_reused_after_publication_failure(self):
        steps = [{'name': 'Publish GitHub release', 'conclusion': 'failure'}]
        self.assertEqual('reuse', scheduler.recovery_kind(steps, 'failure', True))

    def test_setup_failure_allows_fallback(self):
        steps = [{'name': 'Run actions/setup-go@v5', 'conclusion': 'failure'}]
        self.assertEqual('fallback', scheduler.recovery_kind(steps, 'failure', False))

    def test_unknown_compile_error_requires_diagnosis(self):
        steps = [{'name': 'Build ARM64 APK', 'conclusion': 'failure'}]
        self.assertIsNone(scheduler.recovery_kind(steps, 'failure', False))
        self.assertEqual('fallback', scheduler.recovery_kind(steps, 'failure', False, 'No space left on device'))

    def test_timeout_alone_does_not_prove_infrastructure_failure(self):
        self.assertIsNone(scheduler.recovery_kind([], 'timed_out', False))

    def test_running_primary_never_dispatches_fallback(self):
        run = {'id': 10, 'display_title': 'Android ' + 'a' * 40, 'status': 'in_progress', 'conclusion': None}
        with patch.object(scheduler, 'api', return_value={'workflow_runs': [run]}), patch.object(scheduler, 'dispatch') as dispatch:
            scheduler.schedule()
        dispatch.assert_not_called()

    def test_recovery_run_never_recursively_retries(self):
        run = {'id': 10, 'display_title': 'Android ' + 'a' * 40 + ' recovery', 'status': 'completed', 'conclusion': 'failure'}
        with patch.object(scheduler, 'api', return_value={'workflow_runs': [run]}), patch.object(scheduler, 'dispatch') as dispatch:
            scheduler.schedule()
        dispatch.assert_not_called()

    def test_manual_cancellation_is_not_restarted(self):
        run = {'id': 10, 'display_title': 'Android ' + 'a' * 40, 'status': 'completed', 'conclusion': 'cancelled'}
        def api(url, *args, **kwargs):
            if 'workflows/build.yaml/runs' in url:
                return {'workflow_runs': [run]}
            if url.endswith('/artifacts'):
                return {'artifacts': []}
            if url.endswith('/jobs'):
                return {'jobs': []}
            if '/git/ref/' in url:
                return None
            self.fail('Unexpected API call: ' + url)
        with patch.object(scheduler, 'api', api), patch.object(scheduler, 'dispatch') as dispatch:
            scheduler.schedule()
        dispatch.assert_not_called()


class SourceTreeTests(unittest.TestCase):
    def test_candidate_envelope_does_not_hide_later_source_changes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, 'ROOT', pathlib.Path(directory)):
            control.git('init')
            control.git('config', 'user.name', 'Test')
            control.git('config', 'user.email', 'test@example.invalid')
            root = pathlib.Path(directory)
            (root / 'app.txt').write_text('approved code')
            control.git('add', '.')
            expected = control.git('write-tree')
            (root / '.automation').mkdir()
            (root / '.automation/candidate.json').write_text('{}')
            control.git('add', '.')
            control.git('commit', '-m', 'test candidate')
            self.assertEqual(expected, control.source_tree())
            (root / 'app.txt').write_text('unapproved change')
            control.git('add', '.')
            control.git('commit', '-m', 'tampered code')
            self.assertNotEqual(expected, control.source_tree())


if __name__ == '__main__':
    unittest.main()
