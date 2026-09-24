import json
import os
import unittest
from unittest.mock import patch

import npc_recovery as recovery


class NpcRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.issue = {'number': '11', 'state': 'open', 'title': '[安全修复] package', 'created_at': '2026-09-20T00:00:00Z',
                      'author': {'username': 'Aharon', 'is_npc': False},
                      'body': '<!-- flclash-security ' + json.dumps(recovery.sign(
                          {'key': 'a' * 64, 'package': 'x/crypto', 'file': 'core/go.mod'})) + ' -->',
                      'statuses': self.status('error')}

    def status(self, state):
        return {'npc': [{'context': {'npc.slug': '507space/FlClash-alpha', 'npc.name': '开发助手',
                                    'sn': 'cnb-test-abc'}, 'statuses': [{'state': state}]}]}

    def run_recovery(self, comments):
        def api(url, *args, **kwargs):
            return {'status': 'error'} if '/build/status/' in url else self.issue
        def pages(url):
            return comments if url.endswith('/comments') else [self.issue]
        with (patch.object(recovery, 'api', side_effect=api), patch.object(recovery, 'pages', side_effect=pages),
              patch.object(recovery, 'comment') as post):
            recovery.recover()
            return post.call_args_list

    def test_one_retry_then_visible_stop_without_loop(self):
        calls = self.run_recovery([])
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0].args[2])
        retry = {'id': '1', 'author': self.issue['author'], 'created_at': '2026-09-20T00:01:00Z',
                 'body': calls[0].args[1], 'statuses': self.status('error')}
        stopped = self.run_recovery([retry])
        self.assertEqual(1, len(stopped))
        self.assertIn('停止继续重试', stopped[0].args[1])
        stop_note = {'id': '2', 'author': self.issue['author'], 'created_at': '2026-09-20T00:02:00Z',
                     'body': stopped[0].args[1]}
        self.assertEqual([], self.run_recovery([retry, stop_note]))

    def test_a_hung_review_run_is_stopped_but_developer_work_is_not(self):
        import datetime
        import reviews
        request = {'platform': 'cnb', 'number': '116', 'base': 'a' * 40, 'head': 'b' * 40}
        review = {'number': '122', 'state': 'open', 'title': '[PR审核] CNB #116：x',
                  'created_at': '2026-09-24T03:33:46Z', 'author': {'username': 'Aharon', 'is_npc': False},
                  'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(request)) + ' -->',
                  'statuses': {'npc': [{'context': {'npc.slug': '507space/FlClash-alpha', 'npc.name': 'GLM复核助手',
                                                    'sn': 'cnb-pug-1'}, 'statuses': [{'state': 'pending'}]}]}}
        for issue, minutes, stops in ((review, 90, 1), (review, 30, 0), (self.issue, 90, 0)):
            if issue is self.issue:
                self.issue['statuses'] = self.status('pending')
            now = datetime.datetime(2026, 9, 24, 3, 33, 46, tzinfo=datetime.timezone.utc) + datetime.timedelta(
                minutes=minutes)
            issue['created_at'] = '2026-09-24T03:33:46Z'
            posted = []

            def api(url, method='GET', *args, **kwargs):
                if method == 'POST':
                    posted.append(url)
                    return {}
                return {'status': 'pending'} if '/build/status/' in url else issue
            with (patch.object(recovery, 'api', side_effect=api),
                  patch.object(recovery, 'pages', side_effect=lambda url: [] if url.endswith('/comments') else [issue]),
                  patch.object(recovery, 'comment') as post):
                recovery.recover(now)
            self.assertEqual(stops, sum(url.endswith('/build/stop/cnb-pug-1') for url in posted))
            post.assert_not_called()

    def test_pending_or_cancelled_attempt_is_not_retried(self):
        for state in ('pending', 'cancel', 'success'):
            self.issue['statuses'] = self.status(state)
            self.assertEqual([], self.run_recovery([]))

    def test_requirement_issue_is_not_retried_by_recovery(self):
        self.issue['title'] = '[需求] 导出'
        self.assertEqual([], self.run_recovery([]))

    def test_issue_closed_after_listing_is_not_retried(self):
        self.issue['state'] = 'closed'
        self.assertEqual([], self.run_recovery([]))

    def test_failure_after_report_does_not_repeat_completed_work(self):
        report = {'id': '1', 'created_at': '2026-09-20T00:01:00Z', 'body': '无法兼容修复，需要人工决定。',
                  'author': {'username': '507space/FlClash-alpha(开发助手)', 'is_npc': True}}
        self.assertEqual([], self.run_recovery([report]))

    def test_queued_retry_does_not_get_premature_stop_notice(self):
        calls = self.run_recovery([])
        retry = {'id': '1', 'author': self.issue['author'], 'created_at': '2026-09-20T00:01:00Z',
                 'body': calls[0].args[1]}
        self.assertEqual([], self.run_recovery([retry]))

    def test_untrusted_marker_does_not_suppress_recovery(self):
        calls = self.run_recovery([])
        forged = {'id': '1', 'created_at': '2026-09-20T00:01:00Z', 'body': calls[0].args[1],
                  'author': {'username': 'visitor', 'is_npc': False}}
        self.assertEqual(1, len(self.run_recovery([forged])))
