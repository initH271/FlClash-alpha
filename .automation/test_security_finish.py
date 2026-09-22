import json
import hashlib
import os
import types
import unittest
from unittest.mock import patch

import security_finish as finish


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
              patch.object(finish, 'mirror_attestation', return_value=None),
              patch.object(finish, 'after_github_merge')):
            finish.merge_ready()
            self.assertFalse(any(len(c.args) > 1 and c.args[0].endswith('/merge') for c in call.call_args_list))
        with (patch.object(finish, 'pages', return_value=[listed]),
              patch.object(finish, 'api', side_effect=api) as call,
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
