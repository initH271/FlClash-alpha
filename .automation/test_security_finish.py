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

    def test_mirror_reuses_only_identical_baseline_and_result_trees(self):
        payload = {'base': 'a' * 40, 'source': 'b' * 40, 'head': 'c' * 40, 'tree': 'tree-new'}
        branch = 'automation/security-sync-' + hashlib.sha256((payload['base'] + payload['source']).encode()).hexdigest()[:16]
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test'}):
            pull = {'body': '<!-- flclash-security-mirror ' + json.dumps(finish.sign(payload)) + ' -->',
                    'base': {'sha': payload['base'], 'ref': 'main'},
                    'head': {'sha': payload['head'], 'ref': branch, 'repo': {'full_name': finish.POLICY['github']}}}
            for baseline, expected in [('tree-old', True), ('unrelated', False)]:
                with (patch.object(finish, 'git', side_effect=['', 'b first second', 'tree-old', baseline, 'tree-new', 'tree-new']),
                      patch.object(finish, 'safe_files', return_value=True),
                      patch.object(finish, 'tested_source', return_value={'number': '9'})):
                    self.assertEqual(expected, bool(finish.mirror_attestation(pull)))
            pull['head']['sha'] = 'd' * 40
            with patch.object(finish, 'git') as git:
                self.assertIsNone(finish.mirror_attestation(pull))
                git.assert_not_called()

    def test_mirror_in_progress_serializes_new_cnb_merges(self):
        with (patch.dict(finish.POLICY, {'security_auto_merge': True}),
              patch.object(finish, 'mirror', return_value=True), patch.object(finish, 'merge_one') as merge):
            finish.reconcile()
            merge.assert_not_called()

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

    def test_head_change_after_approval_prevents_merge(self):
        issue = {'number': '26'}
        pull = {'number': '50', 'state': 'open', 'is_wip': False,
                'base': {'ref': 'refs/heads/main', 'sha': 'a' * 40},
                'head': {'ref': 'refs/heads/security/group-go-core', 'sha': 'b' * 40,
                         'repo': {'path': finish.POLICY['cnb']}}}
        approved = False
        def api(url, method='GET', data=None):
            nonlocal approved
            if method == 'POST':
                approved = True
                return {}
            if '/issues/' in url:
                return issue
            return dict(pull, head=dict(pull['head'], sha='c' * 40)) if approved else pull
        with (patch.object(finish, 'pages', side_effect=lambda url: [issue] if '/issues?' in url else [pull]),
              patch.object(finish, 'api', side_effect=api) as call,
              patch.object(finish, 'record', return_value={'group': 'go-core'}),
              patch.object(finish, 'git', return_value=types.SimpleNamespace(returncode=0)),
              patch.object(finish, 'state', return_value='success'),
              patch.object(finish, 'passed_checks', return_value=True),
              patch.object(finish, 'safe_files', return_value=True)):
            finish.merge_one()
            self.assertTrue(approved)
            self.assertFalse(any(len(c.args) > 1 and c.args[1] == 'PUT' for c in call.call_args_list))
