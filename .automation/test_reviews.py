import contextlib
import io
import json
import os
import time
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

    def test_disagreement_gets_one_reconsideration_without_overriding_verdict(self):
        reports = [self.report(reviews.ROLES[0], 'block', 1), self.report(reviews.ROLES[1])]
        issue = dict(self.issue, number='42')
        with (patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}),
              patch.object(reviews, 'describe', return_value='verified diff evidence'),
              patch.object(reviews, 'api') as api):
            reviews.reconsider(self.request, issue, reports)
            self.assertEqual(1, api.call_count)
            body = api.call_args.args[2]['body']
            reports.append({'id': '3', 'created_at': '2026-09-20T00:02:00Z', 'body': body,
                            'author': {'username': 'Aharon', 'is_npc': False}})
            api.reset_mock()
            reviews.reconsider(self.request, issue, reports)
            api.assert_not_called()
            self.assertEqual('failure', reviews.result(self.request, issue, reports))

    def test_malformed_report_is_retried_but_matching_blockers_are_not(self):
        issue = dict(self.issue, number='42')
        with (patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}),
              patch.object(reviews, 'describe', return_value='verified diff evidence'),
              patch.object(reviews, 'api') as api):
            reports = [self.report(role, 'block', 1) for role in reviews.ROLES]
            reviews.reconsider(self.request, issue, reports)
            api.assert_not_called()
            reports[0]['body'] = 'Review complete, but forgot machine format'
            reviews.reconsider(self.request, issue, reports)
            self.assertEqual(1, api.call_count)

    def test_renaming_issue_preserves_signed_identity_and_avoids_duplicate_review(self):
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            issue = {'number': '3', 'title': '人工修改过的标题',
                     'author': {'username': reviews.POLICY['approver'], 'is_npc': False},
                     'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(self.request)) + ' -->'}
            with patch.object(reviews, 'all_issues', return_value=[issue]), patch.object(reviews, 'api', return_value=issue) as api:
                self.assertEqual(issue, reviews.ensure_request(self.request, '提高 GLM 审核轮次'))
                self.assertEqual('PATCH', api.call_args.args[1])
                self.assertEqual({'title': '[PR审核] GitHub #1：提高 GLM 审核轮次'}, api.call_args.args[2])
                self.assertFalse(any(len(c.args) > 1 and c.args[1] == 'POST' for c in api.call_args_list))

    def test_malformed_recheck_gets_one_verdict_only_follow_up(self):
        issue = dict(self.issue, number='42')
        role, other = reviews.ROLES
        with (patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}),
              patch.object(reviews, 'describe', return_value='verified diff evidence'),
              patch.object(reviews, 'api') as api):
            reports = [self.report(other)]
            malformed = dict(self.report(role), body='报告写完了，但忘了机器结论行')
            reports.append(malformed)
            reviews.reconsider(self.request, issue, reports)
            recheck = api.call_args.args[2]['body']
            self.assertIn('有界复核', recheck)
            owner = {'username': 'Aharon', 'is_npc': False}
            reports.append({'id': '5', 'created_at': '2026-09-20T00:02:00Z', 'body': recheck, 'author': owner})
            api.reset_mock()
            reviews.reconsider(self.request, issue, reports)
            api.assert_not_called()
            reports.append(dict(malformed, id='6', created_at='2026-09-20T00:03:00Z'))
            reviews.reconsider(self.request, issue, reports)
            follow_up = api.call_args.args[2]['body']
            self.assertIn('不要重新审核', follow_up)
            self.assertIn('FLCLASH_REVIEW', follow_up)
            reports.append({'id': '7', 'created_at': '2026-09-20T00:04:00Z', 'body': follow_up, 'author': owner})
            reports.append(dict(malformed, id='8', created_at='2026-09-20T00:05:00Z'))
            api.reset_mock()
            reviews.reconsider(self.request, issue, reports)
            api.assert_not_called()

    def test_requirement_pull_carries_the_acceptance_criteria_to_reviewers(self):
        body = '## 要改什么\n\n清掉提示\n\n## 验收标准\n\nflutter analyze 输出 No issues found!\n\n## 不做什么\n\n不发版\n\n## 影响范围\n\nFlutter UI\n'
        owner = {'body': body, 'author': {'username': reviews.POLICY['approver'], 'is_npc': False}}
        with patch.object(reviews, 'api', return_value=owner) as api:
            brief = reviews.requirement_brief({'head': {'ref': 'refs/heads/automation/req-111'}})
        self.assertTrue(api.call_args.args[0].endswith('/issues/111'))
        self.assertIn('需求 #111', brief)
        self.assertIn('No issues found!', brief)
        self.assertIn('必须判 block', brief)
        with patch.object(reviews, 'api', return_value=owner) as api:
            self.assertEqual('', reviews.requirement_brief({'head': {'ref': 'fix/wake-on-green'}}))
            api.assert_not_called()
        visitor = dict(owner, author={'username': 'visitor', 'is_npc': False})
        with patch.object(reviews, 'api', return_value=visitor):
            self.assertEqual('', reviews.requirement_brief({'head': {'ref': 'automation/req-111'}}))

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


class _capture:
    """Capture what a command prints while a test runs it."""

    def __enter__(self):
        self.buffer = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.buffer)
        self.redirect.__enter__()
        return self.buffer

    def __exit__(self, *exc):
        return self.redirect.__exit__(*exc)


FIVE = ('Dependency vulnerability gate', 'Automation unit tests', 'Go dependency regression tests',
        'Flutter and Android requirement tests', 'Rust dependency regression tests')


def statuses(states, minutes=10, names=FIVE + ('Paired review gate',)):
    return {'statuses': [{'context': f'cnb/pipeline-{i}({name})', 'state': state,
                          'created_at': stamp(minutes)} for i, (name, state) in enumerate(zip(names, states))]}


def stamp(minutes):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - minutes * 60))


class ReconcileTests(unittest.TestCase):
    def pull(self, ref='refs/heads/automation/req-9'):
        return {'state': 'open', 'number': '12', 'title': '需求实现', 'base': {'sha': 'a' * 40},
                'head': {'sha': 'b' * 40, 'ref': ref}}

    def reconcile(self, checks, ref='refs/heads/automation/req-9', review=None, issue=None):
        pull = self.pull(ref)
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            signed = json.dumps(reviews.sign(reviews.scope('cnb', pull)))
        issue = issue or {'number': '77', 'state': 'open', 'created_at': stamp(120),
                          'body': '<!-- flclash-pr-review ' + signed + ' -->'}

        def api(url, method='GET', data=None, missing=False):
            if url.endswith('/commit-statuses'):
                return checks
            if url.endswith('/status') or '/statuses/' in url:
                return {'statuses': []}
            if '/issues/' in url and url.endswith('/comments'):
                return []
            if url.endswith('/issues/77'):
                return issue
            return pull

        def pages(url, page_key='page', size_key='page_size'):
            return [pull] if url.startswith('https://api.cnb.cool/') and '/pulls?' in url else []
        with (patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}),
              patch.object(reviews, 'api', side_effect=api), patch.object(reviews, 'pages', side_effect=pages),
              patch.object(reviews, 'ensure_request', return_value=issue) as ensure,
              patch.object(reviews, 'existing_review', return_value=review),
              patch.object(reviews, 'close_finished_reviews'), patch.object(reviews, 'requirement_brief',
                                                                            return_value=''), _capture() as printed):
            reviews.reconcile()
        return ensure, printed.getvalue()

    def test_a_pending_pipeline_holds_the_review_inside_the_grace(self):
        ensure, printed = self.reconcile(statuses(('success', 'pending', 'success', 'success', 'success', 'success')))
        ensure.assert_not_called()
        self.assertIn('waiting for CI', printed)
        ensure, printed = self.reconcile({'statuses': [{'context': 'cnb/pipeline-0(Paired review gate)',
                                                       'state': 'success', 'created_at': stamp(10)}]})
        ensure.assert_not_called()
        self.assertIn('waiting for CI', printed)

    def test_a_failed_pipeline_defers_the_review(self):
        ensure, printed = self.reconcile(statuses(('success', 'failure', 'success', 'success', 'success', 'success')))
        ensure.assert_not_called()
        self.assertIn('CI failed, review deferred', printed)

    def test_every_pipeline_green_opens_the_review(self):
        ensure, printed = self.reconcile(statuses(('success',) * 6))
        ensure.assert_called_once()
        self.assertEqual('', ensure.call_args.args[2])
        self.assertNotIn('unsettled', printed)

    def test_an_unsettled_pipeline_past_the_grace_opens_with_a_caveat(self):
        ensure, printed = self.reconcile(statuses(('success', 'pending', 'success', 'success', 'success', 'success'),
                                                  minutes=81))
        ensure.assert_called_once()
        brief = ensure.call_args.args[2]
        self.assertIn('Automation unit tests', brief)
        self.assertIn('未验证', brief)
        self.assertIn('CI unsettled after 80m, review opened', printed)

    def test_security_pulls_wait_but_other_branches_keep_their_timing(self):
        ensure, _ = self.reconcile(statuses(('pending',) * 6), ref='refs/heads/security/group-rust-api')
        ensure.assert_not_called()
        ensure, _ = self.reconcile(statuses(('pending',) * 6), ref='refs/heads/sync/x')
        ensure.assert_called_once()

    def test_an_existing_review_keeps_the_reconsideration_path(self):
        ensure, _ = self.reconcile(statuses(('pending',) * 6), review={'number': '77'})
        ensure.assert_called_once()

    def test_ci_state_only_looks_at_the_pull_request_pipelines(self):
        self.assertEqual('pending', reviews.ci_state({'statuses': [
            {'context': 'cnb/pipeline-1(Dependency vulnerability gate)', 'state': 'success'}]}))
        self.assertEqual('pending', reviews.ci_state(statuses(('success', 'success', 'success', 'success',
                                                              'success', 'pending'))))
        self.assertEqual('failure', reviews.ci_state(statuses(('success', 'success', 'success', 'success',
                                                              'success', 'error'))))
        self.assertEqual('success', reviews.ci_state(statuses(('success', 'success', 'success', 'success',
                                                              'success', 'success'))))
        own = statuses(('success',) * 6)['statuses']
        self.assertEqual('success', reviews.ci_state({'statuses': own + [
            {'context': 'cnb/pipeline-9(FlClash/review-before-ci)', 'state': 'failure'}]}))


if __name__ == '__main__':
    unittest.main()
