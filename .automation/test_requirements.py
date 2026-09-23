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
                    'has_pull': False, 'sha': ''}
        defaults.update(kwargs)
        return req.decide(self.issue, comments or [], rows or [], tree, defaults['contained'],
                          defaults['checks_green'], defaults['review_failed'], defaults['review_text'], self.now,
                          has_pull=defaults['has_pull'], sha=defaults['sha'])

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

    def test_forwarded_pull_merges_once_github_settles(self):
        states = iter([{'mergeable_state': 'unknown'}, {'mergeable_state': 'unstable'}])
        with (patch.object(req, 'api', side_effect=lambda url: next(states)),
              patch.object(req, 'merge_ready') as merge):
            req.merge_when_settled('7', attempts=5, pause=0)
        merge.assert_called_once()

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
