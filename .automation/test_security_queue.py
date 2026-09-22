import datetime
import json
import os
import unittest
from unittest.mock import patch

import security_queue as queue
from security_groups import payload_for


class SecurityQueueTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)
        self.now = datetime.datetime.fromisoformat('2026-09-20T03:00:00+00:00')
        self.payload = payload_for('go-core')
        self.payload['history'] = [{'file': 'core/go.mod', 'ecosystem': 'Go', 'name': 'x/net',
                                   'aliases': ['GO-1'], 'state': '待评估（扫描命中）'}]
        self.issue = {'number': '26', 'created_at': '2026-09-20T02:00:00Z', 'body': 'Notes'}
        self.pull = {'number': '31', 'state': 'open', 'head': {'sha': 'a' * 40}, 'ci_failed': True}

    def attempt(self, status, timestamp='2026-09-20T02:50:00Z'):
        return {'created_at': timestamp, 'statuses': {'npc': [{'context': {
            'npc.slug': '507space/FlClash-alpha', 'npc.name': '开发助手', 'sn': 'cnb-test-1'},
            'statuses': [{'state': status}]}]}}

    def decide(self, comments=None, pc=None, pull=None):
        return queue.decision(self.payload, self.issue, comments or [], pull, pc or [], self.now)

    def checkpoint(self, phase, timestamp='2026-09-20T02:40:00Z'):
        data = {'scope': self.payload['key'] + ':' + queue.revision(self.payload), 'phase': phase}
        return {'created_at': timestamp, 'author': {'username': 'Aharon', 'is_npc': False},
                'body': '<!-- flclash-security-run ' + json.dumps(queue.sign(data)) + ' -->'}

    def test_assessed_unfixed_hit_stays_recorded_without_dispatch(self):
        self.payload['history'][0]['aliases'] = ['GO-2026-5932']
        note = {'author': {'username': 'Aharon', 'is_npc': False},
                'body': 'GO-2026-5932 调用路径不可达，暂无修复，不派开发助手。'}
        self.assertEqual('assessed', self.decide([note])[0])
        self.payload['history'].append({'file': 'core/go.mod', 'ecosystem': 'Go', 'name': 'x/sys',
                                        'aliases': ['GO-2'], 'state': '待评估（扫描命中）'})
        self.assertEqual('start', self.decide([note])[0])

    def test_untouched_group_starts_without_waiting_for_daily_scan(self):
        self.assertEqual('start', self.decide()[0])

    def test_pr_comment_failure_is_recovered_from_same_group(self):
        self.assertEqual('resume', self.decide(pc=[self.attempt('error')], pull=self.pull)[0])

    def test_old_worker_failure_does_not_restart_a_pr_with_no_current_ci_failure(self):
        self.pull['ci_failed'] = False
        self.assertEqual('pr-open', self.decide(pc=[self.attempt('error')], pull=self.pull)[0])

    def test_running_pr_worker_prevents_duplicate_issue_worker(self):
        self.assertEqual('running', self.decide(pc=[self.attempt('pending')], pull=self.pull)[0])

    def test_stalled_worker_keeps_slot_until_platform_confirms_exit(self):
        self.assertEqual('stalled', self.decide(pc=[self.attempt('pending', '2026-09-20T01:00:00Z')])[0])

    def test_one_resume_budget_survives_new_commits_and_repeated_events(self):
        comments = [self.checkpoint('resume')]
        for head in ('a' * 40, 'b' * 40):
            self.pull['head']['sha'] = head
            self.assertEqual('attention', self.decide(comments, [self.attempt('error')], self.pull)[0])

    def test_dispatch_receipt_without_status_reserves_slot(self):
        self.assertEqual('awaiting-start', self.decide([self.checkpoint('start')])[0])
        self.assertEqual('dispatch-stalled', self.decide([self.checkpoint('start', '2026-09-20T01:00:00Z')])[0])

    def test_merged_or_closed_pr_never_restarts_failed_developer(self):
        for merged, expected in ((True, 'rescan'), (False, 'attention')):
            self.pull.update(state='closed', is_merged=merged)
            self.assertEqual(expected, self.decide(pc=[self.attempt('error')], pull=self.pull)[0])

    def test_post_merge_scan_starts_remaining_revision_without_old_attempts(self):
        self.pull.update(state='closed', is_merged=True, included_in_scan=True,
                         updated_at='2026-09-20T02:55:00Z')
        self.assertEqual('start', self.decide(pc=[self.attempt('error')], pull=self.pull)[0])
        self.assertEqual('running', self.decide(comments=[self.attempt('pending', '2026-09-20T02:59:00Z')], pull=self.pull)[0])

    def test_unchanged_revision_after_merge_cannot_reset_retry_budget(self):
        self.pull.update(state='closed', is_merged=True, included_in_scan=True,
                         updated_at='2026-09-20T02:55:00Z')
        self.assertEqual('attention', self.decide([self.checkpoint('resume')], pull=self.pull)[0])

    def test_untrusted_checkpoint_cannot_consume_retry_budget(self):
        item = self.checkpoint('resume')
        item['author']['username'] = 'visitor'
        self.assertEqual('resume', self.decide([item], [self.attempt('error')], self.pull)[0])

    def test_snapshot_preserves_signed_body_and_does_not_repeat_writes(self):
        with patch.object(queue, 'api') as api, patch.object(queue, 'comment') as comment:
            queue.snapshot(self.issue, 'attention', self.pull, None)
            self.issue['body'] = api.call_args.args[2]['body']
            self.assertIn('Notes', self.issue['body'])
            api.reset_mock()
            comment.reset_mock()
            queue.snapshot(self.issue, 'attention', self.pull, None)
            api.assert_not_called()
            comment.assert_not_called()

    def test_global_slots_include_pr_workers_and_fill_untouched_group_first(self):
        issues = []
        for number, group in zip(('26', '27', '28'), ('go-core', 'rust-helper', 'rust-api')):
            payload = dict(self.payload, **payload_for(group))
            payload['history'] = self.payload['history']
            issue = dict(self.issue, number=number, state='open',
                         author={'username': 'Aharon', 'is_npc': False})
            issue['body'] = '<!-- flclash-security-group ' + json.dumps(queue.sign(payload)) + ' -->'
            issues.append(issue)
        pull = dict(self.pull, head={'ref': 'refs/heads/security/group-rust-helper', 'sha': 'a' * 40,
                                     'repo': {'path': '507space/FlClash-alpha'}})
        def pages(url):
            if '/pulls?' in url:
                return [pull]
            if '/pulls/31/comments' in url:
                return [self.attempt('pending', self.now.isoformat())]
            if '/issues/26/comments' in url:
                return [self.attempt('error')]
            return [] if url.endswith('/comments') else issues
        def api(url, method='GET', data=None):
            if url.endswith('/commit-statuses'):
                return {'statuses': []}
            return next(i for i in issues if url.endswith('/' + i['number'])) if method == 'GET' else None
        with (patch.object(queue, 'pages', side_effect=pages), patch.object(queue, 'api', side_effect=api),
              patch.object(queue, 'comment') as comment,
              patch.object(queue.datetime, 'datetime', wraps=datetime.datetime) as clock):
            clock.now.return_value = self.now
            queue.reconcile()
            self.assertEqual(1, comment.call_count)
            self.assertEqual('28', comment.call_args.args[0])
