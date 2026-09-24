import json
import os
import time
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

    def test_waker_dispatches_only_after_every_other_check_passes(self):
        pull = {'state': 'open', 'number': '5', 'base': {'sha': 'b'}, 'head': {'sha': 'h'}}

        def checks(*states):
            names = ('Paired review gate', 'Dependency vulnerability gate', 'Flutter and Android requirement tests')
            statuses = [{'context': f'cnb/pipeline-{i}({name})', 'state': state}
                        for i, (name, state) in enumerate(zip(names, states))]
            statuses.append({'context': 'cnb/pipeline-9(Wake controller after checks)', 'state': 'pending'})
            return {'state': 'pending', 'statuses': statuses}

        def run(*responses, head='h'):
            replies = iter(responses)

            def api(url):
                return {**pull, 'head': {'sha': head}} if url.endswith('/pulls/5') else next(replies)
            with (patch.dict(os.environ, {'CNB_PULL_REQUEST_IID': '5', 'CNB_PULL_REQUEST_SHA': 'h'}),
                  patch.object(wake, 'api', side_effect=api), patch.object(wake, 'dispatch') as dispatch):
                wake.wake_when_green(attempts=3, pause=0)
            return dispatch.call_count

        self.assertEqual(1, run(checks('success', 'success', 'pending'), checks('success', 'success', 'success')))
        self.assertEqual(0, run(checks('success', 'success', 'error')))
        self.assertEqual(0, run(checks('success', 'success', 'success'), head='newer'))
        self.assertEqual(0, run({'statuses': [{'context': 'x(Wake task controller)', 'state': 'success'}]}, {}, {}))

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
