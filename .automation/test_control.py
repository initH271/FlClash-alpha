import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import control
import reviews
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

    def test_pair_review_pins_one_range_and_only_read_only_roles(self):
        text = control.paired_review('a' * 40, 'b' * 40)
        self.assertIn('a' * 40, text)
        self.assertIn('b' * 40, text)
        self.assertEqual(text.count('@507space/FlClash-alpha('), 2)
        self.assertIn('(审查助手)', text)
        self.assertIn('(GLM复核助手)', text)
        self.assertNotIn('(开发助手)', text)
        with self.assertRaises(ValueError):
            control.paired_review('a' * 40, 'b' * 40, '开发助手')

    def test_glm_review_cannot_approve_an_upgrade(self):
        self.assertFalse(control.approved({
            'author': {'username': '507space/FlClash-alpha(GLM复核助手)', 'is_npc': True},
            'body': 'OK',
        }, 'v0.8.98'))


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
        with patch.object(scheduler, 'api', return_value={'workflow_runs': [run]}), patch.object(scheduler, 'dispatch') as dispatch, patch.object(scheduler, 'notify_once') as notify:
            scheduler.schedule()
        dispatch.assert_not_called()
        notify.assert_called_once()

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


OUTCOMES = {'failure': False, 'cancelled': False, 'success': True, 'skipped': True, None: True}
TAG, ISSUE = 'v999.0.0', 7
MAIN, HEAD, UPSTREAM, TREE = 'a' * 40, 'b' * 40, 'c' * 40, 'd' * 40


def outcome_env(outcome):
    env = {'UPSTREAM_APPROVAL_KEY': 'unit-test-key', 'CNB_AUTOMATION_TOKEN': 'unit-test-cnb'}
    if outcome:
        env['FLCLASH_SECURITY_OUTCOME'] = outcome
    cleared = dict(os.environ)
    cleared.pop('FLCLASH_SECURITY_OUTCOME', None)
    return patch.dict(os.environ, dict(cleared, **env), clear=True)


class SecurityHoldTests(unittest.TestCase):
    """Only the HTTP layer (api, pages) and git subprocesses are faked; dispatch runs for real."""

    def approvals(self, outcome):
        posts, pushes = [], []
        branch = f'automation/upstream-{TAG}'
        with outcome_env(outcome):
            request = control.marker({'tag': TAG, 'sha': UPSTREAM, 'upstream': control.POLICY['upstream']})
            envelope = control.sign({'issue': str(ISSUE), 'base': MAIN, 'tree': TREE, 'upstream_sha': UPSTREAM})
        owner_ok = {'author': {'username': control.POLICY['approver'], 'is_npc': False}, 'body': 'OK'}

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if method == 'POST':
                posts.append(url)
                return {}
            if url.endswith(f'/issues/{ISSUE}'):
                return {'body': request, 'state': 'open'}
            if 'workflows/build.yaml/runs' in url:
                return {'workflow_runs': []}
            if url.endswith('/git/ref/heads/main'):
                return {'object': {'sha': MAIN}}
            if url.endswith('/git/ref/heads/' + branch):
                return {'object': {'sha': HEAD}}
            if '/pulls?state=open' in url:
                return [{'number': 1}]
            self.fail('Unexpected API call: ' + url)

        def pages(url, page_key='page', size_key='page_size'):
            if url.endswith('/issues?state=open'):
                return iter([{'title': f'[上游升级] FlClash {TAG}', 'number': ISSUE}])
            return iter([owner_ok])

        def git(*args, check=True, env=None):
            if args[0] == 'push':
                pushes.append(args)
            out = {'rev-parse': HEAD, 'write-tree': TREE}.get(args[0], '')
            return out if check else subprocess.CompletedProcess(['git', *args], 0, out, '')

        with tempfile.TemporaryDirectory() as directory, outcome_env(outcome):
            root = pathlib.Path(directory)
            (root / '.automation').mkdir()
            (root / '.automation/candidate.json').write_text(json.dumps(envelope))
            # active_candidate reads the released version; this one names another upstream, so the candidate stays.
            (root / '.github').mkdir()
            (root / '.github/release.json').write_text(json.dumps({'upstreamVersion': '0.0.0'}))
            with patch.object(control, 'ROOT', root), patch.object(control, 'api', api), \
                    patch.object(control, 'pages', pages), patch.object(control, 'git', git), \
                    patch.object(reviews, 'reconcile') as reconcile, \
                    patch.object(reviews, 'require_candidate'):
                control.approvals()
        return posts, pushes, reconcile

    def test_failed_security_finish_records_approval_but_holds_the_build(self):
        for outcome, dispatches in OUTCOMES.items():
            with self.subTest(outcome=outcome):
                posts, pushes, reconcile = self.approvals(outcome)
                self.assertTrue(pushes)
                reconcile.assert_called_once()
                built = [url for url in posts if url.endswith('/build.yaml/dispatches')]
                self.assertEqual(1 if dispatches else 0, len(built))

    def schedule(self, outcome):
        run = {'id': 10, 'display_title': 'Android ' + MAIN, 'status': 'completed', 'conclusion': 'failure'}
        posts = []

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if method == 'POST':
                posts.append(url)
                return {}
            if 'workflows/build.yaml/runs' in url:
                return {'workflow_runs': [run]}
            if '/git/ref/heads/automation/recovery-' in url:
                return None
            if url.endswith('/artifacts'):
                return {'artifacts': [{'name': 'FlClash-arm64-log-history', 'expired': False}]}
            if url.endswith('/jobs'):
                return {'jobs': [{'steps': [{'name': 'Publish release', 'conclusion': 'failure'}],
                                  'check_run_url': 'https://api.github.com/check-runs/1'}]}
            if url.endswith('/annotations'):
                return []
            self.fail('Unexpected API call: ' + url)

        with outcome_env(outcome), patch.object(scheduler, 'api', api), patch.object(control, 'api', api):
            scheduler.schedule()
        return posts

    def test_failed_security_finish_holds_stopped_build_recovery(self):
        for outcome, dispatches in OUTCOMES.items():
            with self.subTest(outcome=outcome):
                posts = self.schedule(outcome)
                built = [url for url in posts if url.endswith('/build.yaml/dispatches')]
                self.assertEqual(1 if dispatches else 0, len(built))
                self.assertEqual(2 if dispatches else 0, len(posts))


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
