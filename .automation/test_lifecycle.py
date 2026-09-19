import json
import os
import unittest
from unittest.mock import patch

import reviews
import wake


class LifecycleTests(unittest.TestCase):
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

    def test_close_only_signed_reviews_of_finished_prs(self):
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            request = {'platform': 'github', 'number': '2', 'base': 'a' * 40, 'head': 'b' * 40}
            issue = {'number': '3', 'author': {'username': 'Aharon', 'is_npc': False},
                     'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(request)) + ' -->'}
            for pull, expected in (({'state': 'open'}, None), ({'state': 'closed', 'merged': True}, 'completed'),
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
