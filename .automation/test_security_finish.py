import datetime
import json
import hashlib
import io
import os
import types
import unittest
from unittest.mock import patch

import security_finish as finish


NOW = '2026-10-29T10:00:00+00:00'


class SecurityFinishTests(unittest.TestCase):
    def test_compatible_versions_reject_downgrade_major_and_zero_minor_changes(self):
        for old, new, expected in [('1.2.3', '1.4.0', True), ('0.3.1', '0.3.9', True),
                                   ('0.3.1', '0.4.0', False), ('1.2.3', '2.0.0', False),
                                   ('1.2.3', '1.2.2', False), ('1.2.3', '1.3.0-rc1', False)]:
            self.assertEqual(expected, finish.compatible(old, new))

    def safe_go(self, old, new, paths='core/go.mod\0core/go.sum'):
        with patch.object(finish, 'git', side_effect=[paths, old, new]):
            return finish.safe_files('a' * 40, 'b' * 40, 'go-core')

    def test_go_rejects_toolchain_replace_and_scope_changes(self):
        old = 'module core\ngo 1.26.0\nrequire (\n example.org/lib v1.2.3 // indirect\n)'
        self.assertTrue(self.safe_go(old, old.replace('v1.2.3', 'v1.3.0')))
        self.assertFalse(self.safe_go(old, old.replace('1.26.0', '1.27.0')))
        self.assertFalse(self.safe_go(old, old + '\nreplace example.org/lib => ../local'))
        self.assertFalse(self.safe_go(old, old, '.automation/control.py'))
        self.assertFalse(self.safe_go(old, old, 'core/go.sum'))

    def test_rust_rejects_collapsed_duplicate_versions_and_new_git_source(self):
        old = '[[package]]\nname="a"\nversion="1.2.3"\nsource="registry+crates"\n'
        new = old.replace('1.2.3', '1.3.0')
        with patch.object(finish, 'git', side_effect=['services/helper/Cargo.lock', old, new]):
            self.assertTrue(finish.safe_files('a', 'b', 'rust-helper'))
        for candidate in (old.replace('registry+crates', 'git+https://other'), old + new):
            with patch.object(finish, 'git', side_effect=['services/helper/Cargo.lock', old, candidate]):
                self.assertFalse(finish.safe_files('a', 'b', 'rust-helper'))

    def test_green_but_missing_required_checks_cannot_merge(self):
        checks = {'state': 'success', 'statuses': []}
        with patch.object(finish, 'api', return_value=checks):
            self.assertFalse(finish.passed_checks('1'))
        checks['statuses'] = [{'state': 'success', 'context': 'cnb/pipeline(' + name + ')'} for name in finish.CHECKS]
        with patch.object(finish, 'api', return_value=checks):
            self.assertTrue(finish.passed_checks('1'))
        checks['statuses'][0]['state'] = 'error'
        with patch.object(finish, 'api', return_value=checks):
            self.assertFalse(finish.passed_checks('1'))

    def verified(self, *, native=finish.NATIVE_CHECKS, gates=(), sha='c' * 40, merge=0, tree='tree-new'):
        """`native` successes, one gate row per entry in `gates`; the merge-tree writes `tree`."""
        checks = {'sha': sha, 'statuses': [{'state': 'success', 'context': 'cnb/pipeline(' + name + ')'}
                                           for name in native]
                  + [{'state': gate, 'context': 'cnb/pipeline-9(Paired review gate)'} for gate in gates]}
        merged = types.SimpleNamespace(returncode=merge, stdout=('' if merge else tree) + '\n')
        with patch.object(finish, 'api', return_value=checks), patch.object(finish, 'git',
                side_effect=['', merged, 'tree-new']):
            return finish.passed_checks('1', {'base': 'a' * 40, 'head': 'b' * 40})

    def test_the_review_gate_row_never_decides_what_was_verified(self):
        self.assertTrue(self.verified())
        for gate in ('pending', 'error', 'failure', 'success'):
            self.assertTrue(self.verified(gates=(gate,)), gate)
        self.assertTrue(self.verified(gates=('error', 'pending')))

    def test_every_native_check_and_the_tree_are_still_required(self):
        for missing in finish.NATIVE_CHECKS:
            native = [c for c in finish.NATIVE_CHECKS if c != missing]
            self.assertFalse(self.verified(native=native), missing)
        self.assertFalse(self.verified(sha='not-a-sha'))
        self.assertFalse(self.verified(merge=1))
        self.assertFalse(self.verified(tree='tree-old'))

    def test_a_pending_or_failed_native_check_still_blocks(self):
        for state in ('pending', 'error', 'failure'):
            checks = {'sha': 'c' * 40, 'statuses': [
                {'state': 'success', 'context': c} for c in finish.NATIVE_CHECKS[1:]]
                + [{'state': state, 'context': 'cnb/pipeline-8(' + finish.NATIVE_CHECKS[0] + ')'},
                   {'state': 'error', 'context': 'cnb/pipeline-9(Paired review gate)'}]}
            with (patch.object(finish, 'api', return_value=checks), patch.object(finish, 'git')):
                self.assertFalse(finish.passed_checks('1', {'base': 'a' * 40, 'head': 'b' * 40}))

    def test_passed_checks_reads_the_review_verdict_nowhere(self):
        checks = {'sha': 'c' * 40, 'statuses': [
            {'state': 'success', 'context': 'cnb/pipeline(' + name + ')'} for name in finish.NATIVE_CHECKS]}
        merged = types.SimpleNamespace(returncode=0, stdout='tree-new\n')
        with (patch.object(finish, 'api', return_value=checks), patch.object(finish, 'state') as review,
              patch.object(finish, 'git', side_effect=['', merged, 'tree-new'])):
            self.assertTrue(finish.passed_checks('1', {'base': 'a' * 40, 'head': 'b' * 40}))
            self.assertTrue(finish.passed_checks('1'))
            review.assert_not_called()

    def test_old_ci_tree_is_not_valid_for_current_merge(self):
        checks = {'state': 'success', 'sha': 'c' * 40, 'statuses': [
            {'state': 'success', 'context': 'cnb/pipeline(' + name + ')'} for name in finish.CHECKS]}
        request = {'base': 'a' * 40, 'head': 'b' * 40}
        with (patch.object(finish, 'api', return_value=checks), patch.object(finish, 'git', side_effect=[
                '', types.SimpleNamespace(returncode=0, stdout='tree-new\n'), 'tree-old'])):
            self.assertFalse(finish.passed_checks('1', request))

    def test_mirror_authorization_cannot_be_modified(self):
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test'}):
            payload = {'head': 'a' * 40}
            pull = {'body': '<!-- flclash-security-mirror ' + json.dumps(finish.sign(payload)) + ' -->'}
            self.assertEqual(payload, finish.mirror_record(pull))
            pull['body'] = pull['body'].replace('a' * 40, 'b' * 40)
            self.assertIsNone(finish.mirror_record(pull))

    def test_forward_attestation_requires_current_cnb_head_and_base(self):
        payload = {'base': 'a' * 40, 'head': 'c' * 40, 'tree': 'tree-new', 'cnb_number': '8'}
        branch = 'automation/security-sync-' + hashlib.sha256((payload['base'] + payload['head']).encode()).hexdigest()[:16]
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test'}):
            pull = {'body': '<!-- flclash-security-mirror ' + json.dumps(finish.sign(payload)) + ' -->',
                    'base': {'sha': payload['base'], 'ref': 'main'},
                    'head': {'sha': payload['head'], 'ref': branch, 'repo': {'full_name': finish.POLICY['github']}}}
            for base, expected in [(payload['base'], True), ('b' * 40, False)]:
                source = {'number': '8', 'state': 'open', 'base': {'ref': 'refs/heads/main', 'sha': base},
                          'head': {'sha': payload['head'], 'repo': {'path': finish.POLICY['cnb']}}}
                with (patch.object(finish, 'api', return_value=source),
                      patch.object(finish, 'state', return_value='success'),
                      patch.object(finish, 'passed_checks', return_value=True),
                      patch.object(finish, 'git', side_effect=['tree-new', types.SimpleNamespace(returncode=0)]),
                      patch.object(finish, 'safe_files', return_value=True),
                      patch.object(finish, 'find_request', return_value={'number': '9'})):
                    self.assertEqual(expected, bool(finish.mirror_attestation(pull)))

    def test_mirror_in_progress_serializes_new_cnb_merges(self):
        with (patch.dict(finish.POLICY, {'security_auto_merge': True}),
              patch.object(finish, 'mirror', return_value=True), patch.object(finish, 'merge_one') as merge):
            finish.reconcile()
            merge.assert_not_called()

    def test_manually_closed_forwarding_pr_is_not_reopened_or_merged(self):
        with (patch.object(finish, 'api', side_effect=[{'state': 'open'}, [{'number': 9}]]) as api,
              patch.object(finish, 'notify_once') as notify, patch.object(finish, 'pages') as pages):
            finish.forward_pull({'number': '26'}, {'number': '8', 'head': {'sha': 'b' * 40}}, 'a' * 40)
            pages.assert_not_called()
            notify.assert_called_once()
            self.assertEqual(2, api.call_count)

    def test_valid_forwarding_merges_only_github_with_expected_head(self):
        payload = {'base': 'a' * 40, 'head': 'b' * 40, 'tree': 'tree', 'cnb_number': '8'}
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test'}):
            target = {'number': 9, 'body': '<!-- flclash-security-mirror ' + json.dumps(finish.sign(payload)) + ' -->',
                      'base': {'ref': 'main'}, 'head': {'repo': {'full_name': finish.POLICY['github']}}}
            def api(url, method='GET', data=None):
                if '/issues/' in url:
                    return {'state': 'open'}
                return [] if method == 'GET' else {'merged': True}
            with (patch.object(finish, 'api', side_effect=api) as call,
                  patch.object(finish, 'pages', return_value=[target]),
                  patch.object(finish, 'mirror_attestation', return_value='verified'),
                  patch.object(finish.pause, 'paused', return_value=None),
                  patch.object(finish, 'after_github_merge') as follow):
                finish.forward_pull({'number': '26'}, {'number': '8', 'head': {'sha': payload['head']}}, payload['base'])
                writes = [c for c in call.call_args_list if len(c.args) > 1]
                self.assertEqual(1, len(writes))
                self.assertEqual(finish.GH + '/pulls/9/merge', writes[0].args[0])
                self.assertEqual(payload['head'], writes[0].args[2]['sha'])
                follow.assert_called_once_with(payload['head'])

    def test_merge_ready_requires_paired_review_and_signed_forwarding(self):
        pull = {'number': 9, 'draft': False, 'mergeable_state': 'clean', 'head': {'sha': 'b' * 40, 'ref': 'automation/security-sync-abcd'},
                'base': {'ref': 'main'}}
        listed = {'number': 9, 'head': {'ref': pull['head']['ref'], 'repo': {'full_name': finish.POLICY['github']}},
                  'base': {'ref': 'main'}}
        def api(url, method='GET', data=None):
            if url.endswith('/status'):
                return {'statuses': [{'context': 'FlClash/paired-review', 'state': 'success'}]}
            if url.endswith('/pulls/9'):
                return pull
            return {'merged': True, 'sha': 'c' * 40} if method == 'PUT' else None
        with (patch.object(finish, 'pages', return_value=[listed]),
              patch.object(finish, 'api', side_effect=api) as call,
              patch.object(finish.pause, 'paused', return_value=None),
              patch.object(finish, 'mirror_attestation', return_value=None),
              patch.object(finish, 'after_github_merge')):
            finish.merge_ready()
            self.assertFalse(any(len(c.args) > 1 and c.args[0].endswith('/merge') for c in call.call_args_list))
        with (patch.object(finish, 'pages', return_value=[listed]),
              patch.object(finish, 'api', side_effect=api) as call,
              patch.object(finish.pause, 'paused', return_value=None),
              patch.object(finish, 'mirror_attestation', return_value='verified'),
              patch.object(finish, 'after_github_merge') as follow):
            finish.merge_ready()
            follow.assert_called_once_with('c' * 40)

    def test_closed_master_prevents_forwarding(self):
        with patch.object(finish, 'api', return_value={'state': 'closed'}), patch.object(finish, 'pages') as pages:
            finish.forward_pull({'number': '26'}, {}, 'a' * 40)
            pages.assert_not_called()

    def test_cnb_ahead_opens_a_github_pr_without_rewriting_either_main(self):
        with (patch.object(finish, 'api', return_value={'object': {'sha': 'a' * 40}}),
              patch.object(finish, 'git', side_effect=[
                  '', '', 'b' * 40, types.SimpleNamespace(returncode=1), types.SimpleNamespace(returncode=0)]),
              patch.object(finish, 'sync_branch') as push,
              patch.object(finish, 'handoff_cnb_main') as handoff,
              patch.object(finish, 'ensure_scan') as scan):
            self.assertFalse(finish.mirror())
        push.assert_not_called()
        handoff.assert_called_once_with('a' * 40, 'b' * 40)
        scan.assert_called_once_with('a' * 40)

    def test_unrelated_divergence_leaves_both_mains_unchanged(self):
        with (patch.object(finish, 'api', return_value={'object': {'sha': 'a' * 40}}),
              patch.object(finish, 'git', side_effect=[
                  '', '', 'b' * 40, types.SimpleNamespace(returncode=1), types.SimpleNamespace(returncode=1)]),
              patch.object(finish, 'sync_branch') as push,
              patch.object(finish, 'handoff_cnb_main') as handoff,
              patch.object(finish, 'ensure_scan') as scan):
            finish.mirror()
        push.assert_not_called()
        handoff.assert_not_called()
        scan.assert_called_once()

    def test_branch_scan_does_not_redispatch_after_two_failures(self):
        sha = 'a' * 40
        failed = {'head_sha': sha, 'status': 'completed', 'conclusion': 'failure'}
        with patch.object(finish, 'api', return_value={'workflow_runs': [failed, failed]}) as api:
            finish.ensure_branch_scan(sha, 'automation/req-1')
            self.assertEqual(1, api.call_count)

    def test_rescan_dispatch_is_deduplicated_and_failure_budget_is_bounded(self):
        sha = 'a' * 40
        for status, conclusion in [('in_progress', None), ('completed', 'success')]:
            with patch.object(finish, 'api', return_value={'workflow_runs': [
                    {'head_sha': sha, 'status': status, 'conclusion': conclusion}]}) as api:
                finish.ensure_scan(sha)
                self.assertEqual(1, api.call_count)
        failed = {'head_sha': sha, 'status': 'completed', 'conclusion': 'failure'}
        with patch.object(finish, 'api', return_value={'workflow_runs': [failed, failed]}) as api:
            with self.assertRaises(RuntimeError):
                finish.ensure_scan(sha)
            self.assertEqual(1, api.call_count)

    def test_rescan_reads_the_scan_job_when_a_run_was_cancelled(self):
        sha = 'a' * 40
        cancelled = {'id': 7, 'head_sha': sha, 'status': 'completed', 'conclusion': 'cancelled'}

        def responder(scan_conclusion):
            def api(path, *args):
                if path.endswith('/jobs'):
                    return {'jobs': [{'name': 'Dependency vulnerability scan', 'conclusion': scan_conclusion},
                                     {'name': 'track', 'conclusion': 'cancelled'}]}
                if path.endswith('/dispatches'):
                    return {}
                return {'workflow_runs': [cancelled, dict(cancelled, id=8)]}
            return api

        with patch.object(finish, 'api', side_effect=responder('success')) as api:
            finish.ensure_scan(sha)
            self.assertNotIn('/dispatches', ' '.join(call.args[0] for call in api.call_args_list))
        with patch.object(finish, 'api', side_effect=responder('cancelled')) as api:
            finish.ensure_scan(sha)
            self.assertTrue(api.call_args_list[-1].args[0].endswith('/dispatches'))
        with patch.object(finish, 'api', side_effect=lambda path, *args: (
                {'jobs': []} if path.endswith('/jobs')
                else {'workflow_runs': [dict(cancelled, id=n) for n in range(5)]})):
            with self.assertRaises(RuntimeError):
                finish.ensure_scan(sha)

    def test_head_change_prevents_forwarding_and_never_approves_on_cnb(self):
        issue = {'number': '26', 'state': 'open'}
        pull = {'number': '50', 'state': 'open', 'is_wip': False,
                'base': {'ref': 'refs/heads/main', 'sha': 'a' * 40},
                'head': {'ref': 'refs/heads/security/group-go-core', 'sha': 'b' * 40,
                         'repo': {'path': finish.POLICY['cnb']}}}
        reads = 0
        def api(url, method='GET', data=None):
            nonlocal reads
            if '/git/ref/' in url:
                return {'object': {'sha': 'a' * 40}}
            if '/issues/' in url:
                return issue
            reads += 1
            return pull if reads == 1 else dict(pull, head=dict(pull['head'], sha='c' * 40))
        def git(*args, **kwargs):
            if args[0] == 'merge-base':
                return types.SimpleNamespace(returncode=int(args[2] == 'b' * 40))
            return ''
        with (patch.object(finish, 'pages', side_effect=lambda url: [issue] if '/issues?' in url else [pull]),
              patch.object(finish, 'api', side_effect=api) as call,
              patch.object(finish, 'record', return_value={'group': 'go-core'}),
              patch.object(finish, 'git', side_effect=git),
              patch.object(finish, 'state', return_value='success'),
              patch.object(finish, 'passed_checks', return_value=True),
              patch.object(finish, 'safe_files', return_value=True),
              patch.object(finish, 'forward_pull') as forward):
            finish.merge_one()
            forward.assert_not_called()
            self.assertFalse(any(len(c.args) > 1 for c in call.call_args_list))


RELEASE = {'source': 'release', 'head': 'a' * 40, 'pull': 12, 'since': '2026-10-29T09:00:00Z',
           'minutes': 30, 'evidence': 'build.yaml 运行未结束', 'issue': '217'}
HOLD = {'source': 'hold', 'head': '', 'ref': 'automation/security-sync-bbbbbbbbbbbbbbbb',
        'branch': 'automation/security-sync-bbbbbbbbbbbbbbbb', 'since': '2026-10-29T09:00:00Z'}


class ReleaseLockTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test'})
        env.start()
        self.addCleanup(env.stop)

    def forwarding(self, lock, ref='automation/security-sync-' + 'b' * 16, printed=None):
        payload = {'base': 'a' * 40, 'head': 'b' * 40, 'tree': 'tree', 'cnb_number': '8'}
        target = {'number': 9, 'body': '<!-- flclash-security-mirror ' + json.dumps(finish.sign(payload)) + ' -->',
                  'base': {'ref': 'main'}, 'head': {'ref': ref, 'repo': {'full_name': finish.POLICY['github']}}}

        def api(url, method='GET', data=None):
            return {'state': 'open'} if '/issues/' in url else []
        out = printed or io.StringIO()
        with (patch.object(finish, 'api', side_effect=api) as call, patch.object(finish, 'pages', return_value=[target]),
              patch.object(finish, 'mirror_attestation', return_value='verified'),
              patch.object(finish, 'after_github_merge') as follow,
              patch.object(finish.pause, 'paused', return_value=lock) as paused,
              patch('sys.stdout', out)):
            finish.forward_pull({'number': '26'}, {'number': '8', 'head': {'sha': payload['head']}}, payload['base'])
            return call, follow, paused

    def test_a_locked_main_never_merges_a_forwarded_repair(self):
        for lock in (RELEASE, HOLD):
            call, follow, paused = self.forwarding(lock)
            follow.assert_not_called()
            self.assertFalse(any(len(c.args) > 1 and c.args[0].endswith('/merge') for c in call.call_args_list))
            self.assertEqual(('main', 'automation/security-sync-' + 'b' * 16), paused.call_args.args)
            self.assertEqual({}, paused.call_args.kwargs)

    def test_a_hold_defers_a_forwarded_repair_without_a_merge_request(self):
        out = io.StringIO()
        call, follow, paused = self.forwarding(HOLD, printed=out)
        self.assertEqual({}, paused.call_args.kwargs)
        self.assertEqual('main', paused.call_args.args[0])
        self.assertFalse(any(len(c.args) > 1 for c in call.call_args_list))
        self.assertIn('automation/security-sync-' + 'b' * 16
                      + ' held by owner; deferring merge of GitHub PR #9', out.getvalue())

    def test_a_release_defers_a_forwarded_repair_naming_the_head_sha(self):
        out = io.StringIO()
        self.forwarding(RELEASE, printed=out)
        self.assertIn('release in flight (' + 'a' * 12 + '); deferring merge of GitHub PR #9', out.getvalue())

    def test_an_open_main_still_merges_the_forwarded_repair(self):
        payload = {'base': 'a' * 40, 'head': 'b' * 40, 'tree': 'tree', 'cnb_number': '8'}
        target = {'number': 9, 'body': '<!-- flclash-security-mirror ' + json.dumps(finish.sign(payload)) + ' -->',
                  'base': {'ref': 'main'}, 'head': {'ref': 'automation/security-sync-x', 'repo': {'full_name': finish.POLICY['github']}}}

        def api(url, method='GET', data=None):
            if '/issues/' in url:
                return {'state': 'open'}
            return [] if method == 'GET' else {'merged': True}
        with (patch.object(finish, 'api', side_effect=api), patch.object(finish, 'pages', return_value=[target]),
              patch.object(finish, 'mirror_attestation', return_value='verified'),
              patch.object(finish, 'after_github_merge') as follow,
              patch.object(finish.pause, 'paused', return_value=None) as paused):
            finish.forward_pull({'number': '26'}, {'number': '8', 'head': {'sha': payload['head']}}, payload['base'])
        follow.assert_called_once_with(payload['head'])
        self.assertEqual(('main', 'automation/security-sync-x'), paused.call_args.args)
        self.assertEqual({}, paused.call_args.kwargs)


class MergeReadyTests(unittest.TestCase):
    def setUp(self):
        reset = patch.object(finish.pause, '_release', None)
        reset.start()
        self.addCleanup(reset.stop)
        self.writes = []

    def listed(self, ref, sha, number=None):
        return {'number': number or abs(hash((ref, sha))) % 1000,
                'head': {'ref': ref, 'repo': {'full_name': finish.POLICY['github']}}, 'base': {'ref': 'main'}}

    def pull(self, ref, sha):
        return {'number': 1, 'draft': False, 'mergeable_state': 'clean', 'head': {'sha': sha, 'ref': ref},
                'base': {'ref': 'main'}}

    def api(self, pulls, detail=41):
        def api(url, method='GET', data=None):
            self.writes.append((method, url))
            if url.endswith('/status'):
                return {'statuses': [{'context': 'FlClash/paired-review', 'state': 'success'}]}
            if method == 'PUT':
                return {'merged': False}
            for ref, sha in pulls:
                if url.endswith('/pulls/' + str(self.listed(ref, sha)['number'])) or url.endswith('/pulls/' + str(detail)):
                    return dict(self.pull(ref, sha), number=detail)
            raise AssertionError('unexpected read ' + url)
        return api

    def run_merge_ready(self, pulls, comments=(), listed=None):
        self.writes = []
        listed = listed or [self.listed(ref, sha) for ref, sha in pulls]
        with (patch.object(finish, 'pages', return_value=listed), patch.object(finish, 'api', side_effect=self.api(pulls)),
              patch.object(finish, 'mirror_attestation', return_value='verified'),
              patch.object(finish, 'after_github_merge'),
              patch.object(finish.pause, 'pages', side_effect=self.reads(comments))):
            finish.merge_ready()

    def reads(self, comments):
        def pages(url, *args, **kwargs):
            return [{'body': body, 'created_at': '', 'author': {}}
                    if isinstance(body, str) else dict(body) for body in comments]
        return pages

    def merges(self):
        return [url for method, url in self.writes if method == 'PUT']

    def test_a_release_stops_every_merge_and_says_so_once_per_requirement(self):
        posted = []
        with patch.object(finish.pause, 'paused', return_value=RELEASE) as paused, \
                patch.object(finish.pause, 'comment', side_effect=lambda number, body: posted.append((number, body))):
            self.run_merge_ready([('automation/req-9', 'c' * 40), ('automation/security-sync-x', 'd' * 40)])
        self.assertEqual([], self.merges())
        self.assertEqual(['main', 'main'], [call.args[0] for call in paused.call_args_list])
        self.assertEqual(['9'], [number for number, _ in posted])
        body = posted[0][1]
        self.assertTrue(body.startswith(finish.pause.REQUIREMENT_DEFERRED.format('a' * 40)))
        self.assertIn('GitHub PR #12', body)
        self.assertNotIn('草稿', body)
        mark = finish.pause.REQUIREMENT_DEFERRED.format('a' * 40)
        with patch.object(finish.pause, 'paused', return_value=RELEASE), \
                patch.object(finish.pause, 'comment') as again:
            self.run_merge_ready([('automation/req-9', 'c' * 40)], comments=[mark])
        again.assert_not_called()

    def test_an_owner_hold_only_prints(self):
        with patch.object(finish.pause, 'paused', return_value=HOLD), \
                patch.object(finish.pause, 'comment') as post, patch('sys.stdout', new_callable=io.StringIO) as out:
            self.run_merge_ready([('automation/req-9', 'c' * 40)])
        post.assert_not_called()
        self.assertEqual([], self.merges())
        self.assertIn('automation/req-9 held by owner; deferring merge', out.getvalue())

    def test_an_open_main_still_merges(self):
        with patch.object(finish.pause, 'paused', return_value=None), patch.object(finish.pause, 'comment') as post:
            self.run_merge_ready([('automation/cnb-main-x', 'c' * 40)])
        post.assert_not_called()
        self.assertEqual(1, len(self.merges()))

    def test_a_hold_on_the_running_dispatch_waits_instead_of_forwarding(self):
        owner = {'username': finish.POLICY['approver'], 'is_npc': False}
        hold = {'created_at': NOW, 'body': 'HOLD', 'author': owner}
        release = {'created_at': '2026-10-29T10:30:00+00:00', 'body': 'RELEASE', 'author': owner}
        listing = self.listed('automation/req-9', 'c' * 40, 41)
        request = [listing]
        # A running dispatch holds a pending approved-build, so the release is the only pause.
        upstream = [{'head': {'ref': 'automation/upstream-v0.9.3', 'sha': 'a' * 40,
                              'repo': {'full_name': finish.POLICY['github']}},
                     'base': {'ref': 'main'}, 'body': ''}]
        pending = [{'context': 'FlClash/approved-build', 'state': 'pending', 'created_at': NOW}]

        def read(url, *args, **kwargs):
            return list(upstream) if '/pulls?' in url else []

        with (patch.object(finish.pause, 'api', return_value={'statuses': pending}),
              patch.object(finish.pause, 'pages', side_effect=read),
              patch.object(finish.pause, 'status', return_value=None),
              patch('sys.stdout', new_callable=io.StringIO)):
            self.assertEqual('hold', finish.pause.paused('main', 'automation/req-9', [hold])['source'])
            posted = []
            with patch.object(finish.pause, 'comment', side_effect=lambda n, b: posted.append((n, b))):
                self.run_merge_ready([('automation/req-9', 'c' * 40)], comments=[hold], listed=request)
            self.assertEqual([], self.merges())
            self.assertEqual([], posted)
            self.run_merge_ready([('automation/req-9', 'c' * 40)], comments=[hold, release], listed=request)
        self.assertEqual([finish.GH + '/pulls/41/merge'], self.merges())

    def test_a_held_requirement_waits_while_a_repair_merges(self):
        pulls = [(41, 'automation/req-9', 'c' * 40), (42, 'automation/security-sync-' + 'e' * 16, 'd' * 40)]
        listed = [self.listed(ref, sha, number) for number, ref, sha in pulls]
        numbered = {number: (ref, sha) for number, ref, sha in pulls}
        owner = {'username': finish.POLICY['approver'], 'is_npc': False}
        held = {'created_at': '2026-10-29T09:00:00Z', 'body': 'HOLD', 'author': owner}

        def api(url, method='GET', data=None):
            self.writes.append((method, url))
            if url.endswith('/status'):
                return {'statuses': [{'context': 'FlClash/paired-review', 'state': 'success'}]}
            if method == 'PUT':
                return {'merged': False}
            number = int(url.rsplit('/', 1)[-1])
            ref, sha = numbered[number]
            return dict(self.pull(ref, sha), number=number)

        def page(url, *args, **kwargs):
            if '/pulls?' in url:
                return listed
            return [held] if '/issues/9/' in url else []

        with (patch.object(finish, 'pages', side_effect=page), patch.object(finish, 'api', side_effect=api),
              patch.object(finish, 'mirror_attestation', return_value='verified'),
              patch.object(finish, 'after_github_merge'), patch.object(finish.pause, 'pages', side_effect=page),
              patch.object(finish.pause, 'api', return_value=[]),
              patch.object(finish.pause, 'comment') as post):
            finish.merge_ready()
        post.assert_not_called()
        self.assertEqual([finish.GH + '/pulls/42/merge'], self.merges())
