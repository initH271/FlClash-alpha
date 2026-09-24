import datetime
import os
import unittest
from unittest.mock import patch

import requirements as req


BODY = """## 要改什么

加快日志导出

## 验收标准

导出包含 coverage.txt

## 不做什么

不改节点

## 影响范围

Go core

## 允许改自动化配置

未勾选

## 相关文件或界面

core/log_history.go
"""


class RequirementTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)
        self.now = datetime.datetime.fromisoformat('2026-09-22T03:00:00+00:00')
        self.issue = {'number': '9', 'title': '[需求] 导出', 'state': 'open', 'body': BODY}
        self.scope = req.parse(BODY)['scope']

    def marker(self, phase, rung, tree, at, scope=None):
        payload = {'issue': '9', 'scope': scope or self.scope, 'phase': phase, 'rung': rung, 'tree': tree}
        return {'created_at': at, 'body': req.envelope(payload)}

    def attempt(self, state, at, role='开发助手', sn='cnb-test-1', detail=''):
        return {'at': at, 'state': state, 'detail': detail, 'sn': sn, 'role': role}

    def decide(self, comments=None, rows=None, tree='', **kwargs):
        defaults = {'contained': False, 'checks_green': False, 'review_failed': False, 'review_text': '',
                    'has_pull': False, 'sha': '', 'behind': False, 'review_only': False}
        defaults.update(kwargs)
        return req.decide(self.issue, comments or [], rows or [], tree, defaults['contained'],
                          defaults['checks_green'], defaults['review_failed'], defaults['review_text'], self.now,
                          has_pull=defaults['has_pull'], sha=defaults['sha'], behind=defaults['behind'],
                          review_only=defaults['review_only'])

    def test_placeholder_form_is_not_dispatched_twice(self):
        self.issue['body'] = BODY.replace('加快日志导出', '一句话说清要改的行为')
        first = self.decide()
        self.assertEqual('note', first['kind'])
        self.assertIn('要改什么', first['body'])
        comments = [self.marker('invalid', 0, '', '2026-09-22T02:00:00Z', 'form')]
        comments[0]['body'] = req.envelope({'issue': '9', 'scope': 'form', 'phase': 'invalid', 'rung': 0, 'tree': ''})
        self.assertEqual('wait', self.decide(comments)['kind'])

    def test_automation_scope_without_permission_is_incomplete(self):
        self.issue['body'] = BODY.replace('Go core', '自动化配置')
        action = self.decide()
        self.assertEqual('note', action['kind'])
        self.assertIn('允许改自动化配置', action['body'])

    def test_ladder_retries_then_changes_strategy_when_tree_stays_put(self):
        self.assertEqual(60, self.decide()['rung'])
        started = '2026-09-22T02:00:00Z'
        comments = [self.marker('dev', 60, '', started)]
        rows = [self.attempt('error', started)]
        retry = self.decide(comments, rows)
        self.assertEqual(('retry', 60), (retry['phase'], retry['rung']))
        self.assertIn('build/logs/cnb-test-1', retry['instruction'])
        comments.append(self.marker('retry', 60, '', '2026-09-22T02:10:00Z'))
        rows.append(self.attempt('error', '2026-09-22T02:10:00Z', sn='cnb-test-2'))
        diagnose = self.decide(comments, rows)
        self.assertEqual('审查助手', diagnose['role'])
        comments.append(self.marker('diagnose', 60, '', '2026-09-22T02:20:00Z'))
        rows.append(self.attempt('success', '2026-09-22T02:20:00Z', role='审查助手', sn='cnb-test-3'))
        comments.append({'created_at': '2026-09-22T02:25:00Z', 'body': '改 core/log_history.go 的保留段数',
                         'author': {'username': '507space/FlClash-alpha(审查助手)', 'is_npc': True}})
        targeted = self.decide(comments, rows)
        self.assertEqual('targeted', targeted['phase'])
        comments.append(self.marker('targeted', 60, '', '2026-09-22T02:30:00Z'))
        rows.append(self.attempt('success', '2026-09-22T02:30:00Z', sn='cnb-test-4'))
        stopped = self.decide(comments, rows)
        self.assertEqual('stuck', stopped['phase'])

    def test_progress_raises_the_rung_and_a_green_pr_stops_it(self):
        started = '2026-09-22T02:00:00Z'
        comments = [self.marker('dev', 60, '', started)]
        rows = [self.attempt('error', started)]
        raised = self.decide(comments, rows, tree='abc')
        self.assertEqual(120, raised['rung'])
        self.assertIn('abc', raised['instruction'])
        self.assertEqual('forward', self.decide(comments, rows, tree='abc', checks_green=True)['kind'])
        stale = rows + [self.attempt('pending', '2026-09-22T02:40:00Z', sn='cnb-test-2')]
        self.assertEqual('forward', self.decide(comments, stale, tree='abc', checks_green=True)['kind'])

    def test_green_checks_ignore_the_pending_waker(self):
        statuses = {'state': 'pending', 'statuses': [
            {'context': 'cnb/pipeline-1(Flutter and Android requirement tests)', 'state': 'success'},
            {'context': 'cnb/pipeline-2(Wake controller after checks)', 'state': 'pending'}]}
        with patch.object(req, 'api', return_value=statuses):
            self.assertEqual((True, False), req.check_state('5'))
        statuses['statuses'][0]['state'] = 'error'
        with patch.object(req, 'api', return_value=statuses):
            self.assertEqual((False, True), req.check_state('5'))

    def test_green_branch_behind_main_is_synced_before_forwarding(self):
        started = '2026-09-22T02:00:00Z'
        comments = [self.marker('dev', 60, '', started)]
        rows = [self.attempt('success', started)]
        self.assertEqual('sync-main', self.decide(comments, rows, tree='abc', checks_green=True, behind=True)['kind'])
        self.assertEqual('forward', self.decide(comments, rows, tree='abc', checks_green=True)['kind'])

    def test_stopped_ladder_never_holds_back_green_work(self):
        comments = [self.marker('dev', 60, '', '2026-09-22T02:00:00Z'),
                    self.marker('stuck', 120, 'abc', '2026-09-22T02:30:00Z')]
        self.assertEqual('forward', self.decide(comments, tree='abc', checks_green=True)['kind'])
        self.assertEqual('wait', self.decide(comments, tree='abc', review_failed=True)['kind'])
        self.assertEqual('sync-main', self.decide(comments, tree='abc', review_failed=True,
                                                  review_only=True, behind=True)['kind'])
        self.assertEqual('wait', self.decide(comments, tree='abc', review_failed=True, review_only=True)['kind'])
        quota = [self.marker('quota', 60, 'abc', '2026-09-22T02:30:00Z')]
        self.assertEqual('forward', self.decide(quota, tree='abc', checks_green=True)['kind'])
        self.assertEqual('wait', self.decide(quota, tree='abc', review_only=True, behind=True)['kind'])

    def test_main_drift_reports_behind_and_conflicts(self):
        main = {'object': {'sha': 'm' * 40}}
        done = lambda code: type('Done', (), {'returncode': code, 'stdout': 'tree\n'})()
        for ancestor, merge, expected in ((0, 0, (False, False)), (1, 0, (True, False)), (1, 1, (True, True))):
            answers = iter([done(ancestor), done(merge)])

            def git(*args, check=True):
                return '' if args[0] == 'fetch' else next(answers)
            with patch.object(req, 'api', return_value=main), patch.object(req, 'git', side_effect=git):
                self.assertEqual(expected, req.main_drift('s' * 40))

    def test_sync_main_pushes_a_merge_commit_to_the_requirement_branch(self):
        calls = []

        def git(*args, check=True):
            calls.append(args)
            if args[0] == 'merge-tree':
                return type('Done', (), {'returncode': 0, 'stdout': 'tree-1\nextra\n'})()
            return 'new-commit' if args[0] == 'commit-tree' else ''
        with (patch.object(req, 'api', return_value={'object': {'sha': 'm' * 40}}),
              patch.object(req, 'git', side_effect=git), patch.object(req, 'comment') as note,
              patch('control.sync_branch') as push):
            req.sync_main('9', 's' * 40)
        self.assertIn(('commit-tree', 'tree-1', '-p', 's' * 40, '-p', 'm' * 40,
                       '-m', 'Merge main into automation/req-9'), calls)
        push.assert_called_once_with('automation/req-9', 'new-commit')
        self.assertIn('合入', note.call_args.args[1])

    def test_open_github_pull_only_fast_forwards_to_the_new_commit(self):
        pull = {'number': 4, 'head': {'sha': 'o' * 40}, 'html_url': 'https://github.com/x/pull/4'}
        for ancestor, pushes in ((0, 1), (1, 0)):
            def git(*args, check=True):
                if args[0] == 'merge-base':
                    return type('Done', (), {'returncode': ancestor})()
                return 'tree'
            with (patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}),
                  patch.object(req, 'git', side_effect=git), patch.object(req, 'pages', return_value=[]),
                  patch.object(req, 'pull_for', return_value={'number': '12'}),
                  patch.object(req, 'api', return_value={'object': {'sha': 'm' * 40}}) as api,
                  patch.object(req, 'push_github') as push, patch.object(req, 'comment'),
                  patch.object(req, 'settle') as settle):
                req.advance(self.issue, '9', 'n' * 40, pull)
            self.assertEqual(pushes, push.call_count)
            self.assertEqual(pushes, settle.call_count)
            if pushes:
                self.assertEqual('PATCH', api.call_args.args[1])
                self.assertIn('n' * 40, api.call_args.args[2]['body'])
        with patch.object(req, 'git') as git:
            req.advance(self.issue, '9', 'o' * 40, pull)
            git.assert_not_called()

    def test_a_timed_out_gate_counts_once_the_review_has_passed(self):
        statuses = {'statuses': [
            {'context': 'cnb/pipeline-1(Flutter and Android requirement tests)', 'state': 'success'},
            {'context': 'cnb/pipeline-2(Paired review gate)', 'state': 'error'}]}
        pull = {'number': '5', 'base': {'sha': 'b'}, 'head': {'sha': 'h'}}
        for review, expected in (('success', (True, False)), ('failure', (False, True))):
            with patch.object(req, 'api', return_value=statuses), patch.object(req, 'state', return_value=review):
                self.assertEqual(expected, req.check_state('5', pull))
        with patch.object(req, 'api', return_value=statuses), patch.object(req, 'state') as review:
            self.assertEqual((False, True), req.check_state('5'))
            review.assert_not_called()

    def test_forwarded_pull_merges_once_github_settles(self):
        states = iter([{'mergeable_state': 'unknown'}, {'mergeable_state': 'unstable'}, {'merged': True}])
        with (patch.object(req, 'api', side_effect=lambda url: next(states)),
              patch.object(req, 'merge_ready') as merge):
            self.assertTrue(req.merge_when_settled('7', attempts=5, pause=0))
        merge.assert_called_once()
        states = iter([{'mergeable_state': 'blocked'}, {'merged': False}])
        with patch.object(req, 'api', side_effect=lambda url: next(states)), patch.object(req, 'merge_ready'):
            self.assertFalse(req.merge_when_settled('7', attempts=1, pause=0))

    def test_successful_commit_opens_a_pr_instead_of_another_rung(self):
        started = '2026-09-22T02:00:00Z'
        comments = [self.marker('dev', 60, '', started), {
            'created_at': '2026-09-22T02:05:00Z', 'body': '提交 SHA 已满足验收',
            'author': {'username': '507space/FlClash-alpha(开发助手)', 'is_npc': True}}]
        rows = [self.attempt('success', started)]
        opened = self.decide(comments, rows, tree='abc')
        self.assertEqual('open-pr', opened['kind'])
        self.assertEqual('wait', self.decide(comments, rows, tree='abc', has_pull=True)['kind'])
        self.assertIn('开 CNB PR', self.decide()['instruction'])

    def test_running_or_recent_dispatch_does_not_start_another_rung(self):
        started = '2026-09-22T02:50:00Z'
        comments = [self.marker('dev', 60, '', started)]
        self.assertEqual('wait', self.decide(comments)['kind'])
        self.assertEqual('wait', self.decide(comments, [self.attempt('pending', started)])['kind'])
        stalled = [self.marker('dev', 60, '', '2026-09-22T01:00:00Z')]
        again = self.decide(stalled)
        self.assertEqual('dev', again['phase'])

    def test_quota_stops_and_merged_work_closes(self):
        started = '2026-09-22T02:00:00Z'
        comments = [self.marker('dev', 60, '', started)]
        rows = [self.attempt('error', started, detail='账户额度不足')]
        self.assertEqual('quota', self.decide(comments, rows)['phase'])
        self.assertEqual('close', self.decide(contained=True)['kind'])

    def test_changed_acceptance_restarts_at_the_first_rung(self):
        comments = [self.marker('dev', 240, 'old', '2026-09-22T02:00:00Z', scope='other')]
        action = self.decide(comments)
        self.assertEqual(('dev', 60), (action['phase'], action['rung']))
