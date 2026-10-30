import contextlib
import io
import json
import os
import time
import unittest
from unittest.mock import patch

import reviews
import wake


class _capture:
    """Capture what a command prints while a test runs it."""

    def __enter__(self):
        self.buffer = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.buffer)
        self.redirect.__enter__()
        return self.buffer

    def __exit__(self, *exc):
        return self.redirect.__exit__(*exc)


class LifecycleTests(unittest.TestCase):
    def test_trusted_pr_event_wakes_full_controller_without_listing_anything(self):
        with (patch.dict(os.environ, {'CNB_EVENT': 'pull_request.target'}),
              patch.object(wake, 'dispatch') as dispatch, patch.object(wake, 'pages') as pages):
            wake.wake()
            dispatch.assert_called_once()
            pages.assert_not_called()

    def test_the_schedule_also_wakes_a_security_group_pull(self):
        with (patch.dict(os.environ, {'CNB_EVENT': 'crontab: */15 * * * *'}),
              patch.object(wake, 'pages', side_effect=lambda url: (
                  [{'number': '4', 'head': {'ref': 'refs/heads/security/group-rust-api'}}]
                  if '/pulls?' in url else [])),
              patch.object(wake, 'dispatch') as dispatch):
            wake.wake()
            dispatch.assert_called_once()

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
        self.assertTrue(wake.should_wake(issue, {'author': {'username': 'OCI', 'is_npc': True},
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

    def test_watchdog_wakes_each_stalled_requirement_state_once(self):
        now = 1_790_200_000
        stamp = lambda minutes: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now - minutes * 60))
        issue = {'created_at': stamp(60)}

        def signed(phase, minutes, *states, sn='cnb-a-1'):
            payload = json.dumps({'payload': {'phase': phase}, 'signature': 'x'})
            npc = [{'context': {'npc.name': '开发助手', 'sn': sn}, 'statuses': [{'state': s} for s in states]}]
            return {'id': f'm{minutes}', 'created_at': stamp(minutes),
                    'body': f'<!-- flclash-requirement {payload} -->', 'statuses': {'npc': npc if states else []}}

        green = [{'context': 'x(Flutter and Android requirement tests)', 'state': 'success'}]
        pull = {'head': {'sha': 'abc'}}
        self.assertEqual('', wake.stalled({'created_at': stamp(2)}, [], None, [], now))
        self.assertEqual('open', wake.stalled(issue, [], None, [], now))
        self.assertEqual('', wake.stalled(issue, [signed('stuck', 50)], pull, green, now))
        self.assertEqual('', wake.stalled(issue, [signed('dev', 10)], None, [], now))
        self.assertEqual('stall-m50', wake.stalled(issue, [signed('dev', 50)], None, [], now))
        self.assertEqual('', wake.stalled(issue, [signed('dev', 50, 'pending')], None, [], now))
        self.assertEqual('silent-cnb-a-1', wake.stalled(issue, [signed('dev', 50, 'error')], None, [], now))
        report = {'created_at': stamp(20), 'body': '阶段汇报',
                  'author': {'username': '507space/FlClash-alpha(开发助手)'}}
        self.assertEqual('', wake.stalled(issue, [signed('dev', 50, 'success'), report], None, [], now))
        self.assertEqual('green-abc', wake.stalled(issue, [signed('dev', 50, 'success'), report], pull, green, now))
        forwarded = {'created_at': stamp(5), 'body': '需求已送至 GitHub：https://github.com/x/pull/1'}
        self.assertTrue(wake.stalled(issue, [signed('dev', 50), forwarded], pull, green, now).startswith('merge-'))
        retried = [{'body': f'{wake.WAKE_MARKER} merge-{n} -->'} for n in range(wake.MERGE_RETRIES)]
        self.assertEqual('', wake.stalled(issue, [signed('dev', 50), forwarded, *retried], pull, green, now))
        red = [{'context': 'x(Paired review gate)', 'state': 'error'}]
        quiet = [signed('dev', 90, 'success'), dict(report, created_at=stamp(45))]
        self.assertEqual('idle-abc-1', wake.stalled(issue, quiet, pull, red, now))
        waited = quiet + [{'created_at': stamp(45), 'body': f'{wake.WAKE_MARKER} idle-abc -->'}]
        self.assertEqual('idle-abc-2', wake.stalled(issue, waited, pull, red, now))
        recent = quiet + [{'created_at': stamp(5), 'body': f'{wake.WAKE_MARKER} idle-abc-1 -->'}]
        self.assertEqual('', wake.stalled(issue, recent, pull, red, now))
        spent = quiet + [{'created_at': stamp(45), 'body': f'{wake.WAKE_MARKER} idle-abc-{n} -->'}
                         for n in range(1, wake.IDLE_RETRIES + 1)]
        self.assertEqual('', wake.stalled(issue, spent, pull, red, now))
        busy = [signed('dev', 90, 'success'), dict(report, created_at=stamp(10))]
        self.assertEqual('', wake.stalled(issue, busy, pull, red, now))
        self.assertEqual('idle-abc-1', wake.stalled(issue, [signed('stuck', 90)], pull, red, now))
        self.assertEqual('', wake.stalled(issue, [signed('quota', 90)], pull, red, now))
        self.assertEqual('', wake.stalled(issue, [signed('stuck', 90)], None, [], now))

        owner = {'number': '7', 'title': '[需求] x', 'created_at': stamp(60),
                 'author': {'username': 'Aharon', 'is_npc': False}}
        visitor = {**owner, 'number': '8', 'author': {'username': 'visitor', 'is_npc': False}}
        comments = {'7': [signed('dev', 50, 'error')], '8': [signed('dev', 50, 'error')]}

        def pages(url):
            if url.endswith('/pulls?state=open'):
                return []
            if url.endswith('/issues?state=open'):
                return [owner, visitor]
            return comments[url.split('/issues/')[1].split('/')[0]]
        with (patch.object(wake, 'pages', side_effect=pages), patch.object(wake, 'api'),
              patch.object(wake, 'post_comment') as comment):
            wake.watchdog(now)
            comment.assert_called_once_with('7', f'{wake.WAKE_MARKER} silent-cnb-a-1 -->')
            comments['7'].append({'body': f'{wake.WAKE_MARKER} silent-cnb-a-1 -->'})
            wake.watchdog(now)
            comment.assert_called_once()
        self.assertTrue(wake.should_wake({'state': 'open', 'title': '[需求] x', 'body': ''},
                                         {'author': {'username': 'OCI', 'is_npc': True},
                                          'body': f'{wake.WAKE_MARKER} silent-cnb-a-1 -->'}))

    def test_owner_hold_and_release_wake_but_only_the_bare_word_does(self):
        issue = {'state': 'open', 'title': '[需求] 导出', 'body': ''}
        owner = {'username': 'Aharon', 'is_npc': False}
        for body, expected in (('HOLD', True), ('RELEASE', True), ('\nHOLD\n', True),
                               ('HOLD 一下', False), ('hold', False)):
            self.assertEqual(expected, wake.should_wake(issue, {'author': owner, 'body': body}), body)
        for author in ({'username': 'Aharon', 'is_npc': True}, {'username': 'visitor', 'is_npc': False}):
            self.assertFalse(wake.should_wake(issue, {'author': author, 'body': 'HOLD'}))

    def test_a_held_requirement_raises_no_watchdog_wake(self):
        now = 1_790_200_000
        stamp = lambda minutes: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now - minutes * 60))
        issue = {'created_at': stamp(60)}
        payload = json.dumps({'payload': {'phase': 'dev'}, 'signature': 'x'})
        signed = {'id': 'm50', 'created_at': stamp(50), 'body': f'<!-- flclash-requirement {payload} -->',
                  'statuses': {'npc': [{'context': {'npc.name': '开发助手', 'sn': 'cnb-a-1'},
                                        'statuses': [{'state': 'error'}]}]}}
        hold = {'created_at': stamp(40), 'body': 'HOLD', 'author': {'username': 'Aharon', 'is_npc': False}}
        release = {'created_at': stamp(30), 'body': 'RELEASE', 'author': {'username': 'Aharon', 'is_npc': False}}
        green = [{'context': 'x(Flutter and Android requirement tests)', 'state': 'success'}]
        pull = {'head': {'sha': 'abc'}}
        forwarded = {'created_at': stamp(45), 'body': '需求已送至 GitHub：https://github.com/x/pull/1'}
        self.assertEqual('silent-cnb-a-1', wake.stalled(issue, [signed], None, [], now))
        self.assertEqual('', wake.stalled(issue, [signed, hold], None, [], now))
        self.assertEqual('', wake.stalled(issue, [signed, forwarded, hold], pull, green, now))
        self.assertNotEqual('', wake.stalled(issue, [signed, forwarded, hold, release], pull, green, now))

    def test_a_hold_suppresses_the_idle_wake_exactly_as_it_suppresses_a_stall(self):
        now = 1_790_200_000
        stamp = lambda minutes: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now - minutes * 60))
        issue = {'created_at': stamp(300)}
        marker = '<!-- flclash-requirement {"payload": {"phase": "dev"}, "signature": "x"} -->'
        seeded = {'id': 'm300', 'created_at': stamp(300), 'body': marker,
                  'statuses': {'npc': [{'context': {'npc.slug': '507space/FlClash-alpha', 'npc.name': '开发助手'},
                                        'statuses': [{'state': 'success'}]}]}}
        owner = {'username': 'Aharon', 'is_npc': False}
        report = {'created_at': stamp(60), 'body': '阶段汇报', 'author': {'username': '507space/FlClash-alpha(开发助手)'}}
        pull = {'head': {'sha': 'abc'}}
        red = [{'context': 'x(Paired review gate)', 'state': 'error'}]
        green = [{'context': 'x(Flutter and Android requirement tests)', 'state': 'success'}]
        hold = {'created_at': stamp(50), 'body': 'HOLD', 'author': owner}
        release = {'created_at': stamp(40), 'body': 'RELEASE', 'author': owner}
        for checks, expected in ((red, 'idle-abc-1'), (green, 'green-abc')):
            self.assertEqual(expected, wake.stalled(issue, [seeded, report], pull, checks, now), checks)
            self.assertEqual('', wake.stalled(issue, [seeded, report, hold], pull, checks, now), checks)
        released = [seeded, report, hold, release]
        self.assertEqual('', wake.stalled(issue, released, pull, red, now))
        self.assertEqual('green-abc', wake.stalled(issue, released, pull, green, now))
        self.assertEqual('idle-abc-1', wake.stalled(issue, released[:2], pull, red, now))


    def ci(self, *states, own='Automation unit tests'):
        names = {'Dependency vulnerability gate': 'success', 'Automation unit tests': 'pending',
                 'Go dependency regression tests': 'success', 'Flutter and Android requirement tests': 'success',
                 'Rust dependency regression tests': 'success', 'Paired review gate': 'success'}
        for name, state in zip([name for name in names if name != own], states):
            names[name] = state
        return {'statuses': [{'context': f'cnb/pipeline-{i}({name})', 'state': state}
                             for i, (name, state) in enumerate(names.items())]}

    def run_ci(self, statuses, branch='automation/req-7', head='h' * 40, comments=(), state='open'):
        pull = {'state': state, 'number': '5', 'base': {'sha': 'b' * 40},
                'head': {'sha': head, 'ref': f'refs/heads/{branch}'}}

        def api(url, method='GET', data=None, missing=False):
            return pull if url.endswith('/pulls/5') else statuses
        with (patch.dict(os.environ, {'CNB_PULL_REQUEST_IID': '5', 'CNB_PULL_REQUEST_SHA': 'h' * 40,
                                      'CNB_PULL_REQUEST_BRANCH': branch}),
              patch.object(wake, 'api', side_effect=api), patch.object(wake, 'pages', return_value=list(comments)),
              patch.object(wake, 'post_comment') as comment, patch.object(wake, 'dispatch') as dispatch):
            wake.ci_done('Automation unit tests')
        dispatch.assert_not_called()
        return comment

    def test_ci_done_wakes_once_every_other_pipeline_is_settled(self):
        comment = self.run_ci(self.ci('success', 'error', 'cancel', 'success', 'success'))
        comment.assert_called_once()
        self.assertEqual('7', comment.call_args.args[0])
        self.assertIn('ci-' + 'h' * 40, comment.call_args.args[1])
        self.run_ci(self.ci('success', 'success', 'success', 'success', 'pending')).assert_not_called()
        self.run_ci(self.ci('success', 'success', 'success', 'success', 'success'), comments=[
            {'body': f'<!-- flclash-requirement-wake ci-{"h" * 40} -->'}]).assert_not_called()

    def test_ci_done_ignores_moved_prs_and_other_branches(self):
        self.run_ci(self.ci('success', 'success', 'success', 'success', 'success'), head='other').assert_not_called()
        self.run_ci(self.ci('success', 'success', 'success', 'success', 'success'), state='closed').assert_not_called()
        for branch in ('security/group-x', 'sync/x', 'automation/req-x', 'refs/heads/main'):
            with (patch.dict(os.environ, {'CNB_PULL_REQUEST_BRANCH': branch}),
                  patch.object(wake, 'api') as api, patch.object(wake, 'post_comment') as comment):
                wake.ci_done('Automation unit tests')
                api.assert_not_called()
                comment.assert_not_called()

    def test_ci_done_never_fails_the_pipeline(self):
        from control import HttpStatusError
        for error in (HttpStatusError('boom', 500), RuntimeError('boom')):
            with (patch.dict(os.environ, {'CNB_PULL_REQUEST_BRANCH': 'automation/req-7',
                                          'CNB_PULL_REQUEST_IID': '5', 'CNB_PULL_REQUEST_SHA': 'h'}),
                  patch.object(wake, 'api', side_effect=error), patch.object(wake, 'post_comment') as comment):
                wake.ci_done('Automation unit tests')
                comment.assert_not_called()

    def test_the_quarter_hour_schedule_dispatches_only_while_work_is_open(self):
        owner = {'number': '7', 'title': '[需求] 导出', 'body': '', 'author': {'username': 'Aharon', 'is_npc': False}}
        review = {'number': '8', 'title': '[PR审核] CNB #1', 'body': '<!-- flclash-pr-review {} -->',
                  'author': {'username': 'Aharon', 'is_npc': False}}

        def run(issues, pulls):
            def api(url, method='GET', data=None, missing=False):
                return review
            with (patch.dict(os.environ, {'CNB_EVENT': 'crontab: */15 * * * *'}),
                  patch.object(wake, 'pages', side_effect=lambda url: pulls if '/pulls?' in url else issues),
                  patch.object(wake, 'api', side_effect=api), patch.object(wake, 'dispatch') as dispatch,
                  _capture() as printed):
                wake.wake()
            return dispatch.call_count, printed.getvalue()

        self.assertEqual((0, 'idle\n'), run([], []))
        self.assertEqual(1, run([owner], [])[0])
        self.assertEqual(1, run([], [{'number': '1', 'head': {'ref': 'refs/heads/automation/req-3'}}])[0])
        self.assertEqual(0, run([], [{'number': '1', 'head': {'ref': 'refs/heads/sync/x'}}])[0])
        self.assertEqual(1, run([review], [])[0])

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
