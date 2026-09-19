import json
import os
import unittest
from unittest.mock import patch

import reviews


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.request = {'platform': 'github', 'number': '1', 'base': 'a' * 40, 'head': 'b' * 40}
        self.issue = {'state': 'open', 'created_at': '2026-09-20T00:00:00Z'}

    def report(self, role, verdict='pass', blockers=0):
        return {'author': {'username': f'{reviews.POLICY["cnb"]}({role})', 'is_npc': True},
                'created_at': '2026-09-20T00:01:00Z', 'id': '1',
                'body': 'FLCLASH_REVIEW ' + json.dumps({'request': reviews.identity(self.request),
                                                       'verdict': verdict, 'blockers': blockers})}

    def test_two_independent_passes_required(self):
        reports = [self.report(r) for r in reviews.ROLES]
        self.assertEqual('pending', reviews.result(self.request, self.issue, reports[:1]))
        self.assertEqual('success', reviews.result(self.request, self.issue, reports))

    def test_fake_author_stale_range_and_closed_issue_never_pass(self):
        reports = [self.report(r) for r in reviews.ROLES]
        reports[0]['author']['is_npc'] = False
        self.assertEqual('pending', reviews.result(self.request, self.issue, reports))
        reports = [self.report(r) for r in reviews.ROLES]
        for field in ('head', 'base', 'number', 'platform'):
            request = dict(self.request, **{field: 'changed'})
            self.assertEqual('pending', reviews.result(request, self.issue, reports))
        self.assertEqual('failure', reviews.result(self.request, dict(self.issue, state='closed'), reports))

    def test_blocker_and_later_retraction_override_pass(self):
        reports = [self.report(r) for r in reviews.ROLES]
        blocked = self.report(reviews.ROLES[0], blockers=1)
        blocked['created_at'] = '2026-09-20T00:02:00Z'
        self.assertEqual('failure', reviews.result(self.request, self.issue, reports + [blocked]))
        blocked['body'] = 'Review incomplete; I cannot confirm approval.'
        self.assertEqual('failure', reviews.result(self.request, self.issue, reports + [blocked]))

    def test_request_requires_owner_and_valid_signature(self):
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            envelope = reviews.sign(self.request)
            issue = {'author': {'username': reviews.POLICY['approver'], 'is_npc': False},
                     'body': '<!-- flclash-pr-review ' + json.dumps(envelope) + ' -->'}
            self.assertEqual(self.request, reviews.request_from(issue))
            issue['body'] = issue['body'].replace('b' * 40, 'c' * 40)
            self.assertIsNone(reviews.request_from(issue))

    def test_candidate_missing_or_blocked_review_prevents_promotion(self):
        pull = {'number': 1, 'head': {'sha': 'b' * 40}, 'base': {'sha': 'a' * 40}}
        with patch.object(reviews, 'pages', return_value=[pull]):
            for state in ('pending', 'failure'):
                with patch.object(reviews, 'state', return_value=state), self.assertRaises(ValueError):
                    reviews.require_candidate('b' * 40, 'a' * 40)
            with patch.object(reviews, 'state', return_value='success'):
                reviews.require_candidate('b' * 40, 'a' * 40)
                with self.assertRaises(ValueError):
                    reviews.require_candidate('c' * 40, 'a' * 40)


if __name__ == '__main__':
    unittest.main()
