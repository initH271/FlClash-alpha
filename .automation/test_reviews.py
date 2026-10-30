import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
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


def statuses(states, minutes=10, names=FIVE, gate=None):
    """CI rows as CNB lists them; `gate` adds the row a head pushed before 2-1c may still carry."""
    rows = [{'context': f'cnb/pipeline-{i}({name})', 'state': state,
             'created_at': stamp(minutes)} for i, (name, state) in enumerate(zip(names, states))]
    if gate:
        rows.append({'context': 'cnb/pipeline-9(Paired review gate)', 'state': gate, 'created_at': stamp(minutes)})
    return {'statuses': rows}


def stamp(minutes):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - minutes * 60))


class ReconcileTests(unittest.TestCase):
    def pull(self, ref='refs/heads/automation/req-9'):
        return {'state': 'open', 'number': '12', 'title': '需求实现', 'base': {'sha': 'a' * 40},
                'head': {'sha': 'b' * 40, 'ref': ref}}

    def reconcile(self, checks, ref='refs/heads/automation/req-9', notices=(), issue=None, listed=None):
        pull = self.pull(ref)
        listed = pull if listed is None else listed
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            signed = json.dumps(reviews.sign(reviews.scope('cnb', pull)))
        issue = issue or {'number': '77', 'state': 'open', 'created_at': stamp(120),
                          'author': {'username': 'Aharon', 'is_npc': False},
                          'body': '<!-- flclash-pr-review ' + signed + ' -->'}

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if url.endswith('/commit-statuses'):
                return checks
            if url.endswith('/status') or '/statuses/' in url:
                return {'statuses': []}
            if url.endswith('/issues/77'):
                return issue
            if url.endswith('/pulls/12'):
                return pull
            raise AssertionError(f'unexpected request {method} {url}')

        def pages(url, page_key='page', size_key='page_size'):
            if url.startswith('https://api.cnb.cool/') and '/pulls?' in url:
                return iter([listed])
            if url.endswith('/pulls/12/comments'):
                return iter([{'id': str(100 + i), 'body': body} for i, body in enumerate(notices)])
            return iter([])
        with (patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}),
              patch.object(reviews, 'api', side_effect=api), patch.object(reviews, 'pages', side_effect=pages),
              patch.object(reviews, 'ensure_request', return_value=issue) as ensure,
              patch.object(reviews, 'close_finished_reviews'), patch.object(reviews, 'requirement_brief',
                                                                            return_value=''), _capture() as printed):
            reviews.reconcile()
        return ensure, printed.getvalue()

    def test_a_pending_pipeline_holds_the_review_inside_the_grace(self):
        ensure, printed = self.reconcile(statuses(('success', 'pending', 'success', 'success', 'success')))
        ensure.assert_not_called()
        self.assertIn('waiting for CI', printed)
        # A leftover gate row alone is not CI evidence.
        ensure, printed = self.reconcile({'statuses': [{'context': 'cnb/pipeline-0(Paired review gate)',
                                                       'state': 'pending', 'created_at': stamp(10)}]})
        ensure.assert_not_called()
        self.assertIn('waiting for CI', printed)

    def test_a_pr_without_any_ci_status_waits_inside_the_grace(self):
        # 2-1a: an empty status list used to fall straight through to the review.
        ensure, printed = self.reconcile({'statuses': []}, listed=dict(self.pull(), created_at=stamp(5)))
        ensure.assert_not_called()
        self.assertIn('waiting for CI', printed)

    def test_a_pr_without_a_creation_time_says_so_instead_of_waiting_silently(self):
        ensure, printed = self.reconcile({'statuses': []})
        ensure.assert_not_called()
        self.assertIn('waiting for CI (no PR created_at)', printed)

    def test_the_list_creation_time_survives_the_detail_overwrite(self):
        # CNB's `/pulls/{n}` carries no time field at all; only the list entry does.
        detail = {key: value for key, value in self.pull().items() if key != 'created_at'}
        ensure, printed = self.reconcile({'statuses': []}, listed=dict(detail, created_at=stamp(81)))
        ensure.assert_called_once()
        self.assertIn('CI unsettled after 80m, review opened', printed)

    def test_an_empty_status_list_past_the_grace_opens_without_ci_evidence(self):
        ensure, _ = self.reconcile({'statuses': []}, listed=dict(self.pull(), created_at=stamp(81)))
        brief = ensure.call_args.args[2]
        self.assertIn('没有 CI 证据', brief)
        for name in FIVE:
            self.assertNotIn(name, brief)

    def test_one_young_status_outweighs_an_old_pr(self):
        ensure, printed = self.reconcile(statuses(('pending',) * 5, minutes=10),
                                         listed=dict(self.pull(), created_at=stamp(120)))
        ensure.assert_not_called()
        self.assertIn('waiting for CI', printed)

    def test_a_failed_pipeline_defers_the_review(self):
        ensure, printed = self.reconcile(statuses(('success', 'failure', 'success', 'success', 'success')))
        ensure.assert_not_called()
        self.assertIn('CI failed, review deferred', printed)

    def test_every_pipeline_green_opens_the_review(self):
        ensure, printed = self.reconcile(statuses(('success',) * 5))
        ensure.assert_called_once()
        self.assertEqual('', ensure.call_args.args[2])
        self.assertNotIn('unsettled', printed)

    def test_an_unsettled_pipeline_past_the_grace_opens_with_a_caveat(self):
        ensure, printed = self.reconcile(statuses(('success', 'pending', 'success', 'success', 'success'),
                                                  minutes=81))
        ensure.assert_called_once()
        brief = ensure.call_args.args[2]
        # Names exactly the pipelines that had not finished; the assertion never quotes one itself.
        self.assertRegex(brief, r'^CI 未结束就开审的流水线：\S[^。]*。')
        (unsettled,) = FIVE[1:2]
        self.assertIn(unsettled, brief)
        for name in FIVE[2:]:
            self.assertNotIn(name, brief)
        self.assertIn('未验证', brief)
        self.assertIn('CI unsettled after 80m, review opened', printed)

    def test_the_caveat_names_only_the_pipelines_that_had_not_finished(self):
        ensure, _ = self.reconcile(statuses(('success', 'success', 'success', 'success', 'pending'),
                                           minutes=81))
        brief = ensure.call_args.args[2]
        self.assertIn(FIVE[-1], brief)
        for name in FIVE[:-1]:
            self.assertNotIn(name, brief)

    def test_security_pulls_wait_but_other_branches_keep_their_timing(self):
        ensure, _ = self.reconcile(statuses(('pending',) * 5), ref='refs/heads/security/group-rust-api')
        ensure.assert_not_called()
        ensure, _ = self.reconcile(statuses(('pending',) * 5), ref='refs/heads/sync/x')
        ensure.assert_called_once()

    def test_an_existing_review_keeps_the_reconsideration_path(self):
        link = 'https://cnb.cool/507space/FlClash-alpha/-/issues/77'
        # Found through the real existing_review: by the notice marker, and by the link a pre-marker notice carries.
        for notice in (f'结对审核： {link}\nbase x\n<!-- flclash-review-notice 77 -->', f'结对审核： {link}\nbase x'):
            ensure, printed = self.reconcile(statuses(('pending',) * 5), notices=['无关评论', notice])
            ensure.assert_called_once()
            self.assertNotIn('waiting for CI', printed)
        ensure, printed = self.reconcile(statuses(('pending',) * 5))
        ensure.assert_not_called()
        self.assertIn('waiting for CI', printed)

    def test_github_heads_still_get_the_required_paired_review_status(self):
        # 2-1c removed only the CNB polling job; GitHub branch protection still requires this context.
        pull = {'state': 'open', 'number': '3', 'title': 'x', 'base': {'sha': 'a' * 40},
                'head': {'sha': 'c' * 40, 'ref': 'feature'}}
        posts = []

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if method == 'POST':
                posts.append((url, data))
                return data
            if url.endswith('/pulls/3'):
                return pull
            if url.endswith('/status'):
                return {'statuses': []}
            raise AssertionError(f'unexpected request {method} {url}')

        def pages(url, page_key='page', size_key='page_size'):
            return iter([pull] if url.startswith(reviews.GH) and '/pulls?' in url else [])
        with (patch.object(reviews, 'api', side_effect=api), patch.object(reviews, 'pages', side_effect=pages),
              patch('security_finish.mirror_attestation', return_value=None),
              patch('security_finish.mirror_record', return_value=None),
              patch.object(reviews, 'ensure_request', return_value={'number': '8', 'state': 'closed'}),
              patch.object(reviews, 'withhold'), patch.object(reviews, 'result', return_value='success'),
              patch.object(reviews, 'close_finished_reviews'),
              patch.object(reviews, 'requirement_brief', return_value=''), _capture()):
            reviews.reconcile()
        ((url, data),) = posts
        self.assertEqual(f'{reviews.GH}/statuses/' + 'c' * 40, url)
        self.assertEqual(('FlClash/paired-review', 'success'), (data['context'], data['state']))

    def test_ci_state_only_looks_at_the_pull_request_pipelines(self):
        self.assertEqual('pending', reviews.ci_state({'statuses': [
            {'context': 'cnb/pipeline-1(Dependency vulnerability gate)', 'state': 'success'}]}))
        self.assertEqual('pending', reviews.ci_state(statuses(('success', 'success', 'success', 'pending'))))
        self.assertEqual('pending', reviews.ci_state(statuses(('success', 'success', 'success', 'success', 'pending'))))
        self.assertEqual('failure', reviews.ci_state(statuses(('success', 'success', 'success', 'success', 'error'))))
        for gate in (None, 'pending', 'error'):
            self.assertEqual('success', reviews.ci_state(statuses(('success',) * 5, gate=gate)), gate)
        own = statuses(('success',) * 5)['statuses']
        self.assertEqual('success', reviews.ci_state({'statuses': own + [
            {'context': 'cnb/pipeline-9(FlClash/review-before-ci)', 'state': 'failure'}]}))


class NoticeTests(unittest.TestCase):
    """ensure_request writes the notice and existing_review reads it back, both through the HTTP layer only."""

    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)
        self.pull = {'number': '12', 'base': {'sha': 'a' * 40}, 'head': {'sha': 'b' * 40, 'ref': 'automation/req-9'}}
        self.issues, self.comments = {}, {}

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        path = url.removeprefix(reviews.CNB + '/')
        if method == 'POST' and path == 'issues':
            self.serial = getattr(self, 'serial', 79) + 1  # never reuses the number of a deleted issue
            number = str(self.serial)
            self.issues[number] = dict(data, number=number, state='open', created_at=stamp(1),
                                       author={'username': 'Aharon', 'is_npc': False})
            return self.issues[number]
        if method == 'POST' and path.endswith('/comments'):
            rows = self.comments.setdefault(path, [])
            rows.append({'id': str(500 + len(rows)), 'body': data['body']})
            return rows[-1]
        if method == 'GET' and path.startswith('issues/'):
            found = self.issues.get(path.removeprefix('issues/'))
            if found is None and not missing:
                raise AssertionError(url)
            return found
        raise AssertionError(f'unexpected request {method} {url}')

    def pages(self, url, page_key='page', size_key='page_size'):
        path = url.removeprefix(reviews.CNB + '/')
        if path.startswith('issues?'):
            return iter([{'number': number} for number in self.issues])
        return iter(self.comments.get(path, []))

    def network(self):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(reviews, 'api', side_effect=self.api))
        stack.enter_context(patch.object(reviews, 'pages', side_effect=self.pages))
        stack.enter_context(patch('control.pages', side_effect=self.pages))
        stack.enter_context(patch('review_evidence.git', side_effect=self.git))
        return stack

    @staticmethod
    def git(*args, check=True, env=None):
        """Answer like control.git: stripped stdout with check=True, the finished process with check=False."""
        stdout = {'merge-base': 'c' * 40 + '\n', 'merge-tree': 'd' * 40 + '\n'}.get(args[0], '')
        if check:
            return stdout.strip()
        return subprocess.CompletedProcess(['git', *args], 0, stdout=stdout, stderr='')

    def test_the_notice_names_the_review_issue_on_the_endpoint_existing_review_reads(self):
        with self.network():
            self.assertIsNone(reviews.existing_review(self.pull))
            self.issues['30'] = {'number': '30', 'state': 'open', 'body': 'unrelated'}
            issue = reviews.ensure_request(reviews.scope('cnb', self.pull), '需求实现')
            self.assertEqual(['pulls/12/comments'], list(self.comments))
            (notice,) = self.comments['pulls/12/comments']
            self.assertIn(f'<!-- flclash-review-notice {issue["number"]} -->', notice['body'])
            self.assertNotIn('<!-- flclash-review-notice 12 -->', notice['body'])
            self.assertEqual(issue, reviews.existing_review(self.pull))
            # A new head is a new request, so the old notice does not count for it.
            self.assertIsNone(reviews.existing_review(dict(self.pull, head={'sha': 'c' * 40, 'ref': 'x'})))

    def test_a_review_opened_before_the_marker_is_found_by_its_link(self):
        with self.network():
            request = reviews.scope('cnb', self.pull)
            legacy = {'number': '41', 'state': 'open', 'author': {'username': 'Aharon', 'is_npc': False},
                      'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(request)) + ' -->'}
            self.issues['41'] = legacy
            self.comments['pulls/12/comments'] = [
                {'id': '9', 'body': '请先看日志'},
                {'id': '10', 'body': '结对审核： https://cnb.cool/507space/FlClash-alpha/-/issues/41\n'
                                     f'base `{"a" * 40}` / head `{"b" * 40}`。两位审核者完成且无阻断问题后检查才通过。'}]
            self.assertEqual(legacy, reviews.existing_review(self.pull))
            self.issues['41'] = dict(legacy, author={'username': 'someone', 'is_npc': False})
            self.assertIsNone(reviews.existing_review(self.pull))


DIFF = ('diff --git a/core/a.go b/core/a.go\nindex 1111111..2222222 100644\n--- a/core/a.go\n+++ b/core/a.go\n'
        '@@ -10,2 +12,3 @@ func run()\n-old\n-old2\n+++ looks like a header\n+b\n+c\n@@ -40,0 +45 @@\n+d\n'
        'diff --git a/gone.txt b/gone.txt\ndeleted file mode 100644\n--- a/gone.txt\n+++ /dev/null\n'
        '@@ -1,2 +0,0 @@\n-x\n-y\n')


class PromptTests(unittest.TestCase):
    """What a summoned reviewer is told, built by the real prompt code over the HTTP and git layers only."""

    api, pages = NoticeTests.api, NoticeTests.pages

    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)
        self.pull = {'number': '12', 'base': {'sha': 'a' * 40}, 'head': {'sha': 'b' * 40, 'ref': 'automation/req-9'}}
        self.request = reviews.scope('cnb', self.pull)
        self.issues, self.comments = {}, {}

    @staticmethod
    def git(*args, check=True, env=None):
        """Answer like control.git: stripped stdout with check=True, the finished process with check=False."""
        stdout = {'merge-base': 'c' * 40, 'merge-tree': 'd' * 40, 'rev-parse': 'e' * 40}.get(args[0], '')
        if args[0] == 'diff':
            stdout = DIFF if '-U0' in args else 'core/a.go\0gone.txt\0'
        if check:
            return stdout.strip()
        return subprocess.CompletedProcess(['git', *args], 0, stdout=stdout, stderr='')

    def network(self):
        stack = contextlib.ExitStack()
        for target, fake in (('reviews.api', self.api), ('reviews.pages', self.pages), ('control.pages', self.pages),
                             ('review_evidence.git', self.git), ('reviews.git', self.git)):
            stack.enter_context(patch(target, side_effect=fake))
        return stack

    def earlier_round(self):
        """An older head of the same pull whose GLM report blocked, announced on the pull like a real one."""
        old = dict(self.request, head='9' * 40)
        self.issues['41'] = {'number': '41', 'state': 'closed', 'author': {'username': 'Aharon', 'is_npc': False},
                             'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(old)) + ' -->'}
        verdict = lambda v, n: 'FLCLASH_REVIEW ' + json.dumps({'request': reviews.identity(old), 'verdict': v,
                                                               'blockers': n})
        self.comments['issues/41/comments'] = [
            {'id': '1', 'author': {'username': f'{reviews.POLICY["cnb"]}(GLM复核助手)', 'is_npc': True},
             'body': '阻断 1：core/a.go:12-14 少了空值检查，＠审查助手 请看\n@someone\n' + verdict('block', 1)},
            {'id': '2', 'author': {'username': f'{reviews.POLICY["cnb"]}(审查助手)', 'is_npc': True},
             'body': '审查助手认为可以合并\n' + verdict('pass', 0)}]
        self.comments['pulls/12/comments'] = [{'id': '3', 'body': '<!-- flclash-review-notice 41 -->'}]

    def test_the_review_summon_reserves_posting_reports_progress_and_scopes_the_diff(self):
        self.earlier_round()
        with self.network():
            issue = reviews.ensure_request(self.request, '需求实现')
        body = issue['body']
        for text in ('1 次留给发布最终报告', '取证和进度评论合计最多 39 次', '每审完一个文件或一组验收条目',
                     reviews.PROGRESS, '用到第 38 次时停止取证', '「未完成」状态评论', '审到哪里、还差什么',
                     'git show <head>:<路径>', '路径:起止行号', '上游原样', '不计入 blockers',
                     '- `core/a.go`：12-14、45（+4/−2）', '- `gone.txt`：整个文件删除（+0/−2）',
                     '前几轮的阻断清单', 'core/a.go:12-14 少了空值检查', '逐条对照验收标准原文',
                     '测试替身和被替换函数的签名、返回类型一致', '单测不联网', '不要 mock 掉被测对象本身'):
            self.assertIn(text, body)
        self.assertNotIn('审查助手认为可以合并', body)
        self.assertNotIn('@someone', body)
        self.assertEqual(1, body.count('FLCLASH_REVIEW {'))

    def test_the_bounded_recheck_uses_the_reconsider_budget_instead_of_eight_calls(self):
        issue = {'number': '42', 'state': 'open', 'created_at': '2026-09-20T00:00:00Z'}
        report = lambda role, verdict, n: {
            'id': '1', 'created_at': '2026-09-20T00:01:00Z',
            'author': {'username': f'{reviews.POLICY["cnb"]}({role})', 'is_npc': True},
            'body': 'FLCLASH_REVIEW ' + json.dumps({'request': reviews.identity(self.request), 'verdict': verdict,
                                                   'blockers': n})}
        with self.network():
            reviews.reconsider(self.request, issue, [report('审查助手', 'block', 1), report('GLM复核助手', 'pass', 0)])
        (posted,) = self.comments['issues/42/comments']
        for text in ('取证和进度评论合计最多 11 次', '1 次留给发布最终报告', 'git show <head>:<路径>',
                     '- `core/a.go`：12-14、45（+4/−2）'):
            self.assertIn(text, posted['body'])
        self.assertNotIn('最多8次', posted['body'])

    def test_a_progress_note_is_neither_a_verdict_nor_a_malformed_report(self):
        issue = {'state': 'open', 'created_at': '2026-09-20T00:00:00Z'}
        author = {'username': f'{reviews.POLICY["cnb"]}(GLM复核助手)', 'is_npc': True}
        note = {'id': '1', 'created_at': '2026-09-20T00:01:00Z', 'author': author,
                'body': reviews.PROGRESS + '\n已审 core/a.go，未完成：gone.txt'}
        self.assertEqual({}, reviews.role_reports(self.request, issue, [note]))
        self.assertEqual('pending', reviews.result(self.request, issue, [note]))
        self.assertEqual({'GLM复核助手': 'malformed'},
                         reviews.role_reports(self.request, issue, [dict(note, body='已审 core/a.go')]))

    def test_the_recovery_summon_carries_the_same_budget_and_evidence_rules(self):
        import npc_recovery
        issue = {'title': '[PR审核] CNB #12：x', 'author': {'username': reviews.POLICY['approver'], 'is_npc': False},
                 'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(self.request)) + ' -->'}
        instruction = npc_recovery.task(issue)[3]
        for text in ('1 次留给发布最终报告', '取证和进度评论合计最多 11 次', 'git show <head>:<路径>', '上游原样'):
            self.assertIn(text, instruction)


class WithholdTests(unittest.TestCase):
    def run_withhold(self, ci, grace=(), ref='refs/heads/automation/req-9'):
        rows = statuses(ci)['statuses'] + [
            {'context': 'FlClash/review-before-ci', 'state': state, 'created_at': stamp(30 - i)}
            for i, state in enumerate(grace)]
        posts = []

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if method == 'POST':
                self.assertEqual(f'{reviews.CNB}/statuses/' + 'b' * 40, url)
                posts.append(data['state'])
                return data
            self.assertTrue(url.endswith('/pulls/12/commit-statuses'), url)
            return {'statuses': rows}
        pull = {'number': '12', 'base': {'sha': 'a' * 40}, 'head': {'sha': 'b' * 40, 'ref': ref}}
        with patch.object(reviews, 'api', side_effect=api):
            reviews.withhold(pull)
        return posts

    def test_withhold_marks_unfinished_ci_red_once_and_clears_it_when_every_pipeline_passes(self):
        five = ('success',) * 5
        self.assertEqual(['failure'], self.run_withhold(five[:4] + ('pending',)))
        self.assertEqual(['failure'], self.run_withhold(five[:4] + ('failure',)))
        self.assertEqual([], self.run_withhold(five[:4] + ('pending',), grace=('failure',)))
        self.assertEqual(['failure'], self.run_withhold(five[:4] + ('pending',), grace=('failure', 'success')))
        self.assertEqual([], self.run_withhold(five))
        self.assertEqual(['success'], self.run_withhold(five, grace=('failure',)))
        self.assertEqual([], self.run_withhold(five, grace=('failure', 'success')))
        self.assertEqual([], self.run_withhold(five[:4] + ('pending',), ref='refs/heads/security/group-x'))


def added(sizes):
    """A -U0 diff where each path gains the given number of lines."""
    return ''.join(f'diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{n} @@\n' + '+x\n' * n
                   for path, n in sizes.items())


BIG = dict({f'lib/a/f{i}.dart': 10 for i in range(1, 8)}, **{'lib/b/x.dart': 5, 'core/big.go': 400})
# sha256 of the review body e1313d9e writes for the PromptTests diff; an unsharded PR must keep it.
SMALL_BODY = 'e0d607cb03f4c1dcd824fbc8676ac14c99e61b865cf3efc2b7ea3535d9313489'


class ShardTests(unittest.TestCase):
    """GLM shards for an oversized diff, through the real review code over the HTTP and git layers only."""

    pages = NoticeTests.pages

    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)
        self.pull = {'number': '12', 'state': 'open', 'base': {'sha': 'a' * 40},
                     'head': {'sha': 'b' * 40, 'ref': 'automation/req-9'}}
        self.request = reviews.scope('cnb', self.pull)
        self.issues, self.comments, self.closed, self.diff = {}, {}, [], added(BIG)

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        if url.endswith('/pulls/12'):
            return self.pull
        if method == 'PATCH':
            number = url.rsplit('/', 1)[-1]
            if data.get('state') == 'closed':
                self.closed.append(number)
            self.issues[number].update(data)
            return {}
        return NoticeTests.api(self, url, method, data, missing, timeout)

    def git(self, *args, check=True, env=None):
        """Answer like control.git: stripped stdout with check=True, the finished process with check=False."""
        stdout = {'merge-base': 'c' * 40, 'merge-tree': 'd' * 40, 'rev-parse': 'e' * 40}.get(args[0], '')
        if args[0] == 'diff':
            names = re.findall(r'^diff --git a/\S+ b/(\S+)', self.diff, re.M)
            stdout = self.diff if '-U0' in args else '\0'.join(names)
        if check:
            return stdout.strip()
        return subprocess.CompletedProcess(['git', *args], 0, stdout=stdout, stderr='')

    def network(self):
        stack = contextlib.ExitStack()
        for target, fake in (('reviews.api', self.api), ('reviews.pages', self.pages), ('control.pages', self.pages),
                             ('review_evidence.git', self.git), ('reviews.git', self.git)):
            stack.enter_context(patch(target, side_effect=fake))
        return stack

    def opened(self):
        with self.network():
            main = reviews.ensure_request(self.request, '需求实现')
        parts = [(reviews.request_from(issue), issue) for issue in self.issues.values() if issue is not main]
        return main, sorted(parts, key=lambda part: part[0]['shard']['index'])

    def say(self, issue, role, part, verdict='pass', text=''):
        rows = self.comments.setdefault(f'issues/{issue["number"]}/comments', [])
        rows.append({'id': str(len(rows)), 'created_at': '9999-01-01T00:00:00Z',
                     'author': {'username': f'{reviews.POLICY["cnb"]}({role})', 'is_npc': True},
                     'body': text + '\nFLCLASH_REVIEW ' + json.dumps({
                         'request': reviews.identity(part), 'verdict': verdict, 'blockers': int(verdict != 'pass')})})

    def test_an_oversized_diff_is_grouped_by_directory_within_both_limits(self):
        with self.network():
            groups = reviews.shards(self.request)
        self.assertEqual([['core/big.go'], [f'lib/a/f{i}.dart' for i in range(1, 7)],
                          ['lib/a/f7.dart', 'lib/b/x.dart']], [group['paths'] for group in groups])
        self.assertEqual([(1, 3), (2, 3), (3, 3)], [(group['index'], group['total']) for group in groups])

    def test_a_small_diff_keeps_the_single_review_byte_for_byte(self):
        self.diff = DIFF
        with self.network():
            issue = reviews.ensure_request(self.request, '需求实现')
        self.assertEqual(1, len(self.issues))
        self.assertIn('<!-- flclash-pr-review ' + json.dumps(reviews.sign(self.request)) + ' -->', issue['body'])
        self.assertEqual(SMALL_BODY, hashlib.sha256(issue['body'].encode()).hexdigest())

    def test_each_shard_summons_only_glm_over_its_own_files_under_a_signed_shard(self):
        main, parts = self.opened()
        self.assertEqual(3, len(parts))
        summon = lambda role: f'@{reviews.POLICY["cnb"]}({role})'
        self.assertIn(summon('审查助手'), main['body'])
        self.assertNotIn(summon('GLM复核助手'), main['body'])
        self.assertIn('<!-- flclash-review-shards ' + ','.join(issue['number'] for _, issue in parts) + ' -->',
                      main['body'])
        for part, issue in parts:
            self.assertEqual(self.request, reviews.unsharded(part))
            self.assertIn(summon('GLM复核助手'), issue['body'])
            self.assertNotIn(summon('审查助手'), issue['body'])
            self.assertIn(reviews.identity(part), issue['body'])
            listed = re.findall(r'^- `([^`]+)`', issue['body'], re.M)
            self.assertEqual(part['shard']['paths'], listed)
            forged = issue['body'].replace(json.dumps(part['shard']['paths'])[1:-1], '"lib/b/x.dart"')
            self.assertNotEqual(forged, issue['body'])
            self.assertIsNone(reviews.request_from(dict(issue, body=forged)))
        with self.network():
            self.assertEqual(main, reviews.ensure_request(self.request, '需求实现'))
        self.assertEqual(4, len(self.issues))

    def test_glm_passes_only_when_every_shard_passes(self):
        main, parts = self.opened()
        self.say(main, '审查助手', self.request)
        for part, issue in parts[:2]:
            self.say(issue, 'GLM复核助手', part)
        with self.network():
            self.assertEqual('pending', reviews.state(self.request))
            self.say(parts[2][1], 'GLM复核助手', parts[2][0])
            self.assertEqual('success', reviews.state(self.request))
            self.say(parts[1][1], 'GLM复核助手', parts[1][0], 'block')
            self.assertEqual('failure', reviews.state(self.request))

    def test_review_block_quotes_the_blocking_shard(self):
        import requirements
        main, parts = self.opened()
        self.say(main, '审查助手', self.request)
        self.say(parts[0][1], 'GLM复核助手', parts[0][0], 'block', 'core/big.go:3-5 漏了错误处理')
        with self.network():
            blocked, text = requirements.review_block(self.pull)
        self.assertTrue(blocked)
        self.assertIn('core/big.go:3-5 漏了错误处理', text)

    def listed(self, main):
        return reviews.SHARDS.search(main['body'])[1].split(',')

    def heal(self):
        with self.network():
            return reviews.ensure_request(self.request, '需求实现')

    def test_every_shard_missing_stays_pending_then_is_reopened_and_glm_cannot_pass_on_the_main_issue(self):
        main, parts = self.opened()
        self.say(main, '审查助手', self.request)
        self.say(main, 'GLM复核助手', self.request)
        for _, issue in parts:
            del self.issues[issue['number']]
        with self.network():
            self.assertEqual('pending', reviews.state(self.request))
        healed = self.heal()
        numbers = self.listed(healed)
        self.assertEqual(3, len(numbers))
        self.assertFalse(set(numbers) & {issue['number'] for _, issue in parts})
        self.assertEqual(numbers, self.listed(self.issues[main['number']]))
        for number in numbers:
            self.assertIn(f'https://cnb.cool/{reviews.POLICY["cnb"]}/-/issues/{number}', healed['body'])
        with self.network():
            self.assertEqual('pending', reviews.state(self.request))
            for number in numbers:
                self.say(self.issues[number], 'GLM复核助手', reviews.request_from(self.issues[number]))
            self.assertEqual('success', reviews.state(self.request))

    def test_one_missing_or_closed_shard_behaves_the_same_and_only_it_is_replaced(self):
        for gone in ('deleted', 'closed'):
            with self.subTest(gone):
                self.issues, self.comments = {}, {}
                main, parts = self.opened()
                self.say(main, '审查助手', self.request)
                for part, issue in parts:
                    self.say(issue, 'GLM复核助手', part)
                old = parts[1][1]['number']
                if gone == 'deleted':
                    del self.issues[old]
                else:
                    self.issues[old]['state'] = 'closed'
                with self.network():
                    self.assertEqual('pending', reviews.state(self.request))
                numbers = self.listed(self.heal())
                self.assertEqual(parts[0][1]['number'], numbers[0])
                self.assertEqual(parts[2][1]['number'], numbers[2])
                self.assertNotEqual(old, numbers[1])
                fresh = self.issues[numbers[1]]
                self.assertEqual(parts[1][0], reviews.request_from(fresh))
                self.assertEqual('open', fresh['state'])
                self.assertIn('GLM复核助手', fresh['body'])
                if gone == 'closed':
                    self.assertEqual('closed', self.issues[old]['state'])
                with self.network():
                    self.assertEqual('pending', reviews.state(self.request))
                    self.say(fresh, 'GLM复核助手', parts[1][0])
                    self.assertEqual('success', reviews.state(self.request))
                self.assertEqual(numbers, self.listed(self.heal()))

    def test_healing_keeps_a_block_on_an_open_shard(self):
        main, parts = self.opened()
        self.say(main, '审查助手', self.request)
        self.say(parts[0][1], 'GLM复核助手', parts[0][0], 'block')
        del self.issues[parts[1][1]['number']]
        self.heal()
        with self.network():
            self.assertEqual('failure', reviews.state(self.request))

    def test_no_replacement_when_the_diff_is_unreadable_or_the_main_issue_is_closed(self):
        main, parts = self.opened()
        del self.issues[parts[0][1]['number']]
        count, body = len(self.issues), main['body']
        with patch.object(reviews, 'shards', return_value=[]):
            self.heal()
        self.assertEqual((count, body), (len(self.issues), self.issues[main['number']]['body']))
        with self.network():
            self.assertEqual('pending', reviews.state(self.request))
        self.issues[main['number']]['state'] = 'closed'
        self.heal()
        self.assertEqual((count, body), (len(self.issues), self.issues[main['number']]['body']))
        with self.network():
            self.assertEqual('failure', reviews.state(self.request))

    def test_a_repeated_number_in_the_marker_counts_once(self):
        main, parts = self.opened()
        self.say(main, '审查助手', self.request)
        for part, issue in parts:
            self.say(issue, 'GLM复核助手', part)
        first = parts[0][1]['number']
        main['body'] = main['body'].replace(f'shards {first},', f'shards {first},{first},')
        with self.network():
            self.assertEqual(3, len(reviews.shard_parts(self.request, main)))
            self.assertEqual('success', reviews.state(self.request))

    def test_shards_close_with_their_head_but_not_before(self):
        shard = dict(self.request, shard={'index': 1, 'total': 2, 'paths': ['core/big.go']})
        self.issues['90'] = {'number': '90', 'state': 'open', 'author': {'username': 'Aharon', 'is_npc': False},
                             'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(shard)) + ' -->'}
        with self.network():
            reviews.close_finished_reviews()
            self.assertEqual([], self.closed)
            self.pull['head'] = {'sha': 'f' * 40, 'ref': 'automation/req-9'}
            reviews.close_finished_reviews()
        self.assertEqual(sorted(self.issues), sorted(self.closed))


if __name__ == '__main__':
    unittest.main()
