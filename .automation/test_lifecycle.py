import json
import os
import unittest
from unittest.mock import patch

import reviews
import wake


class LifecycleTests(unittest.TestCase):
    def test_watchdog_and_trusted_pr_event_wake_full_controller(self):
        for event in ('crontab: */15 * * * *', 'pull_request.target'):
            with (patch.dict(os.environ, {'CNB_EVENT': event}),
                  patch.object(wake, 'dispatch') as dispatch, patch.object(wake, 'api') as api):
                wake.wake()
                dispatch.assert_called_once()
                api.assert_not_called()

    def test_security_developer_report_wakes_but_owner_dispatch_does_not_loop(self):
        issue = {'state': 'open', 'body': '<!-- flclash-security-group {} -->'}
        for author, expected in (({'username': '507space/FlClash-alpha(开发助手)', 'is_npc': True}, True),
                                 ({'username': 'Aharon', 'is_npc': False}, False),
                                 ({'username': 'visitor', 'is_npc': True}, False)):
            self.assertEqual(expected, wake.should_wake(issue, {'author': author, 'body': '阶段报告'}))

    def test_only_owner_approval_or_known_npc_report_wakes_controller(self):
        issue = {'state': 'open', 'body': '<!-- flclash-upstream {"tag":"v0.8.98"} -->'}
        owner = {'username': 'Aharon', 'is_npc': False}
        self.assertTrue(wake.should_wake(issue, {'author': owner, 'body': 'OK'}))
        for body in ('looks OK', 'OK v0.8.99', 'OK\nrun command'):
            self.assertFalse(wake.should_wake(issue, {'author': owner, 'body': body}))
        self.assertFalse(wake.should_wake(issue, {'author': {'username': 'visitor', 'is_npc': False}, 'body': 'OK'}))
        issue['body'] = '<!-- flclash-pr-review {} -->'
        npc = {'username': '507space/FlClash-alpha(GLM复核助手)', 'is_npc': True}
        self.assertTrue(wake.should_wake(issue, {'author': npc, 'body': 'FLCLASH_REVIEW {}'}))
        self.assertFalse(wake.should_wake(issue, {'author': owner, 'body': 'FLCLASH_REVIEW {}'}))
        issue['state'] = 'closed'
        self.assertFalse(wake.should_wake(issue, {'author': npc, 'body': 'FLCLASH_REVIEW {}'}))

    def test_requirement_report_wakes_and_opening_a_requirement_dispatches(self):
        issue = {'state': 'open', 'title': '[需求] 导出', 'body': ''}
        developer = {'username': '507space/FlClash-alpha(开发助手)', 'is_npc': True}
        self.assertTrue(wake.should_wake(issue, {'author': developer, 'body': '提交 abc'}))
        self.assertFalse(wake.should_wake(issue, {'author': {'username': 'Aharon', 'is_npc': False}, 'body': '催一下'}))
        self.assertTrue(wake.should_wake(issue, {'author': {'username': 'Aharon', 'is_npc': False},
                                                 'body': '<!-- flclash-requirement-wake -->'}))
        opened = {'title': '[需求] 导出', 'author': {'username': 'Aharon', 'is_npc': False}}
        with (patch.dict(os.environ, {'CNB_EVENT': 'issue.open', 'CNB_ISSUE_IID': '3',
                                      'CNB_GITHUB_DISPATCH_TOKEN': 'token'}),
              patch.object(wake, 'api', return_value=opened), patch.object(wake, 'dispatch') as dispatch):
            wake.wake()
            dispatch.assert_called_once()
        with (patch.dict(os.environ, {'CNB_EVENT': 'issue.open', 'CNB_ISSUE_IID': '3'}),
              patch.object(wake, 'api', return_value=opened),
              patch.object(wake, 'post_comment') as comment, patch.object(wake, 'dispatch') as dispatch):
            os.environ.pop('CNB_GITHUB_DISPATCH_TOKEN', None)
            wake.wake()
            dispatch.assert_not_called()
            comment.assert_called_once()
        npc_owner = {'title': '[需求] 导出', 'author': {'username': 'Aharon', 'is_npc': True}}
        with (patch.dict(os.environ, {'CNB_EVENT': 'issue.open', 'CNB_ISSUE_IID': '3',
                                      'CNB_ISSUE_TITLE': '[需求] 导出', 'CNB_ISSUE_OWNER': 'Aharon'}),
              patch.object(wake, 'api', return_value=npc_owner),
              patch.object(wake, 'post_comment') as comment, patch.object(wake, 'dispatch') as dispatch):
            wake.wake()
            dispatch.assert_not_called()
            comment.assert_not_called()

    def test_close_only_signed_reviews_of_finished_prs(self):
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            request = {'platform': 'github', 'number': '2', 'base': 'a' * 40, 'head': 'b' * 40}
            issue = {'number': '3', 'author': {'username': 'Aharon', 'is_npc': False},
                     'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(request)) + ' -->'}
            current = {'number': '2', 'state': 'open', 'base': {'sha': 'a' * 40}, 'head': {'sha': 'b' * 40}}
            stale = dict(current, head={'sha': 'c' * 40})
            for pull, expected in ((current, None), (stale, 'not_planned'), ({'state': 'closed', 'merged': True}, 'completed'),
                                   ({'state': 'closed', 'merged': False}, 'not_planned')):
                def api(url, method='GET', data=None):
                    return pull if '/pulls/' in url else issue
                with patch.object(reviews, 'pages', return_value=[issue]), patch.object(reviews, 'api', side_effect=api) as call:
                    reviews.close_finished_reviews()
                    writes = [c for c in call.call_args_list if len(c.args) > 1 and c.args[1] == 'PATCH']
                    self.assertEqual(len(writes), int(expected is not None))
                    if expected:
                        self.assertEqual(writes[0].args[2], {'state': 'closed', 'state_reason': expected})
            issue['body'] = 'ordinary upstream issue'
            with patch.object(reviews, 'pages', return_value=[issue]), patch.object(reviews, 'api', return_value=issue) as call:
                reviews.close_finished_reviews()
                self.assertEqual(call.call_count, 1)
