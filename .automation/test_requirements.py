import contextlib
import datetime
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import control
import env_failure
import pause
import requirements as req
import reviews
import security_finish


_real_git = control.git


def local_git(*args, **kwargs):
    """Run git in the patched ROOT, except the fetch the test never needs."""
    return [] if args[:1] == ('fetch',) else _real_git(*args, **kwargs)


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


PULL = {'number': '5', 'state': 'open', 'base': {'sha': 'b' * 40}, 'head': {'sha': 'h' * 40}}


def ci_checks(ci, gate=None, extra=()):
    """Commit statuses as CNB lists them: one row per main.pull_request pipeline, then the gate if it reported."""
    rows = [{'context': f'cnb/pipeline-{i}({name})', 'state': found}
            for i, (name, found) in enumerate(zip(reviews.CI_PIPELINES, ci))]
    if gate:
        rows.append({'context': f'cnb/pipeline-9({req.REVIEW_GATE})', 'state': gate})
    return {'statuses': rows + list(extra)}


def network(checks, pull=PULL, verdicts=('pass', 'pass')):
    """Patch only the HTTP layer so the real check_state and the real review state read these answers."""
    request = reviews.scope('cnb', pull)
    issue = {'number': '77', 'state': 'open', 'created_at': '2026-09-22T02:00:00Z',
             'author': {'username': 'Aharon', 'is_npc': False},
             'body': '<!-- flclash-pr-review ' + json.dumps(reviews.sign(request)) + ' -->'}
    reports = [{'id': str(i), 'created_at': '2026-09-22T02:10:00Z',
                'author': {'username': f'{control.POLICY["cnb"]}({role})', 'is_npc': True},
                'body': 'FLCLASH_REVIEW ' + json.dumps({'request': reviews.identity(request), 'verdict': verdict,
                                                        'blockers': 0 if verdict == 'pass' else 1})}
               for i, (role, verdict) in enumerate(zip(reviews.ROLES, verdicts))]

    def api(url, method='GET', data=None, missing=False, timeout=60):
        if url.endswith('/commit-statuses'):
            return checks
        if url.endswith('/issues/77'):
            return issue
        raise AssertionError(f'unexpected request {method} {url}')

    def pages(url, page_key='page', size_key='page_size'):
        if '/issues?state=open' in url:
            return iter([{'number': '77'}])
        if url.endswith('/issues/77/comments'):
            return iter(reports)
        return iter([])
    return contextlib.ExitStack(), [patch.object(control, 'api', side_effect=api),
                                    patch.object(control, 'pages', side_effect=pages),
                                    patch.object(reviews, 'api', side_effect=api),
                                    patch.object(reviews, 'pages', side_effect=pages)]


def real_check_state(checks, pull=PULL, verdicts=('pass', 'pass')):
    stack, patches = network(checks, pull, verdicts)
    with stack:
        for item in patches:
            stack.enter_context(item)
        return req.check_state('5', pull)


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
                    'has_pull': False, 'sha': '', 'behind': False, 'review_only': False, 'hold': '',
                    'env_failure': None}
        defaults.update(kwargs)
        return req.decide(self.issue, comments or [], rows or [], tree, defaults['contained'],
                          defaults['checks_green'], defaults['review_failed'], defaults['review_text'], self.now,
                          has_pull=defaults['has_pull'], sha=defaults['sha'], behind=defaults['behind'],
                          review_only=defaults['review_only'], hold=defaults['hold'],
                          env_failure=defaults['env_failure'])

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

    def test_green_checks_ignore_the_review_grace_marker(self):
        grace = [{'context': 'cnb/pipeline-9(FlClash/review-before-ci)', 'state': 'pending'}]
        self.assertEqual((True, False), real_check_state(ci_checks(('success',) * 5, extra=grace)))
        self.assertEqual((False, True), real_check_state(ci_checks(('error',) + ('success',) * 4, extra=grace)))

    def test_green_branch_behind_main_is_synced_before_forwarding(self):
        started = '2026-09-22T02:00:00Z'
        comments = [self.marker('dev', 60, '', started)]
        rows = [self.attempt('success', started)]
        self.assertEqual('sync-main', self.decide(comments, rows, tree='abc', checks_green=True, behind=True)['kind'])
        self.assertEqual('forward', self.decide(comments, rows, tree='abc', checks_green=True)['kind'])

    def test_stopped_ladder_never_holds_back_green_work(self):
        comments = [self.marker('dev', 60, '', '2026-09-22T02:00:00Z'),
                    self.marker('stuck', 120, 'abc', '2026-09-22T02:30:00Z')]
        self.assertEqual('forward', self.decide(comments, tree='abc', checks_green=True)['kind'])
        self.assertEqual('wait', self.decide(comments, tree='abc', review_failed=True)['kind'])
        self.assertEqual('sync-main', self.decide(comments, tree='abc', review_failed=True,
                                                  review_only=True, behind=True)['kind'])
        self.assertEqual('wait', self.decide(comments, tree='abc', review_failed=True, review_only=True)['kind'])
        quota = [self.marker('quota', 60, 'abc', '2026-09-22T02:30:00Z')]
        self.assertEqual('forward', self.decide(quota, tree='abc', checks_green=True)['kind'])
        self.assertEqual('wait', self.decide(quota, tree='abc', review_only=True, behind=True)['kind'])

    def check_state(self, ci, verdicts=('pass', 'pass')):
        """Run the real check_state over these pipeline states, the gate still pending, and real review reports."""
        return real_check_state(ci_checks(ci, gate='pending'), verdicts=verdicts)

    def runtime_inputs(self, ci):
        """Drive the real reconcile over a forwarded requirement PR and report what it reached for."""
        issue = {'number': '9', 'state': 'open', 'title': '[需求] 导出', 'body': BODY,
                 'author': {'username': 'Aharon', 'is_npc': False}, 'created_at': '2026-09-22T02:00:00Z'}
        comments = [self.marker('dev', 60, '', '2026-09-22T02:01:00Z'),
                    {'created_at': '2026-09-22T02:03:00Z', 'body': '提交 abc，等待自动化检查',
                     'author': {'username': '507space/FlClash-alpha(开发助手)', 'is_npc': True}}]
        pull = {'number': '5', 'state': 'open', 'title': '[需求] 导出',
                'base': {'sha': 'b' * 40},
                'head': {'sha': 'c' * 40, 'ref': 'refs/heads/automation/req-9',
                         'repo': {'path': control.POLICY['cnb']}}}
        statuses = ci_checks(ci, gate='pending')
        import security_finish
        with (patch.object(req, 'merge_ready') as merge, patch.object(req, 'sync_main') as sync,
              patch.object(req, 'forward') as forward, patch.object(req, 'act') as act,
              patch.object(req, 'main_drift', return_value=(False, False)),
              patch.object(req, 'review_block', return_value=(False, '')),
              patch.object(security_finish, 'dispatch_workflow', return_value=None, create=True),
              patch.object(control, 'pages', side_effect=lambda url: (
                  [pull] if '/pulls?' in url else [issue] if '/issues?' in url else comments)),
              patch.object(control, 'api', side_effect=lambda url, *a, **k: pull if '/pulls/5' in url
                           and url.endswith('/pulls/5') else statuses if url.endswith('/commit-statuses')
                           else issue if url.endswith('/issues/9') else {'object': {'sha': 'a' * 40}}),
              patch.object(req, 'state', return_value='success'),
              patch.object(req, 'pull_statuses', return_value=req.control.gating_statuses(statuses)),
              patch.object(req, 'branch_sha', return_value='c' * 40),
              patch.object(req, 'contained', return_value=False),
              patch.object(req, 'foreign_commits', return_value=[]),
              patch.object(req, 'attempts', return_value=[]),
              patch.object(control, 'git', return_value='tree')):
            req.reconcile()
        return forward, sync, merge, act

    def test_a_green_review_before_ci_settles_never_forwards(self):
        for ci in (('success',) * 4 + ('pending',), ('success',) * 4 + ('failure',)):
            green, failed = self.check_state(ci)
            self.assertFalse(green)
            self.assertEqual(ci[-1] == 'failure', failed)
            forward, sync, merge, act = self.runtime_inputs(ci)
            forward.assert_not_called()
            sync.assert_not_called()
            merge.assert_not_called()
            for call in act.call_args_list:
                self.assertNotEqual('forward', call.args[1]['kind'])

    def test_a_req_pr_forwards_only_after_every_pipeline_succeeded(self):
        self.assertEqual((True, False), self.check_state(('success',) * 5))
        forward, sync, merge, act = self.runtime_inputs(('success',) * 5)
        self.assertEqual('forward', act.call_args.args[1]['kind'])
        forward.assert_not_called()
        sync.assert_not_called()

    def test_main_drift_reports_behind_and_conflicts(self):
        main = {'object': {'sha': 'm' * 40}}
        done = lambda code: type('Done', (), {'returncode': code, 'stdout': 'tree\n'})()
        for ancestor, merge, expected in ((0, 0, (False, False)), (1, 0, (True, False)), (1, 1, (True, True))):
            answers = iter([done(ancestor), done(merge)])

            def git(*args, check=True):
                return '' if args[0] == 'fetch' else next(answers)
            with patch.object(control, 'api', return_value=main), patch.object(control, 'git', side_effect=git):
                self.assertEqual(expected, req.main_drift('s' * 40))

    def test_sync_main_pushes_a_merge_commit_to_the_requirement_branch(self):
        calls = []

        def git(*args, check=True):
            # Mirror control.git: check=True returns stripped stdout, check=False the process result.
            calls.append(args)
            stdout = {'merge-tree': 'tree-1\nextra\n', 'commit-tree': 'new-commit\n'}.get(args[0], '')
            if check:
                return stdout.strip()
            return type('Done', (), {'returncode': 0, 'stdout': stdout})()
        with (patch.object(control, 'api', return_value={'object': {'sha': 'm' * 40}}),
              patch.object(control, 'git', side_effect=git), patch.object(control, 'comment') as note,
              patch.object(control, 'sync_branch') as push):
            req.sync_main('9', 's' * 40)
        self.assertIn(('commit-tree', 'tree-1', '-p', 's' * 40, '-p', 'm' * 40,
                       '-m', 'Merge main into automation/req-9', '-m', 'FlClash-Actor: controller'), calls)
        push.assert_called_once_with('automation/req-9', 'new-commit')
        self.assertIn('合入', note.call_args.args[1])
        (record,) = req.markers([{'body': note.call_args.args[1]}])
        self.assertEqual(('sync', 'new-commit', 's' * 40), (record['phase'], record['head'], record['from']))

    def test_a_sync_shaped_head_whose_pipelines_may_reuse_ci_needs_the_signed_sync_record(self):
        import ci_paths
        with tempfile.TemporaryDirectory() as directory:
            git = lambda *args: ci_paths.run_git('-C', directory, '-c', 'user.name=t', '-c', 'user.email=t@t', *args)
            git('init', '-q')
            for path, text in (('.cnb.yml', 'python3 .automation/ci_paths.py reuse'), ('README.md', 'a'),
                               ('lib/a.dart', 'b')):
                (pathlib.Path(directory) / path).parent.mkdir(exist_ok=True)
                (pathlib.Path(directory) / path).write_text(text)
            git('add', '-A')
            tree = git('write-tree')
            base = git('commit-tree', tree, '-m', 'base')
            own = git('commit-tree', tree, '-p', base, '-m', 'own')
            head = git('commit-tree', tree, '-p', own, '-p', base, '-m', 'Merge main into automation/req-9',
                       '-m', 'FlClash-Actor: controller')
            signed = {'body': req.envelope({'issue': '9', 'phase': 'sync', 'head': head, 'from': own})}
            forged = {'body': req.envelope({'issue': '9', 'phase': 'sync', 'head': own, 'from': base})}
            with patch.object(control, 'ROOT', pathlib.Path(directory)):
                self.assertTrue(req.reuse_unvouched('9', head, [forged]))
                self.assertFalse(req.reuse_unvouched('9', head, [signed]))
                self.assertFalse(req.reuse_unvouched('9', own, []))
                self.assertFalse(req.reuse_unvouched('8', head, []))

    def test_an_unvouched_reuse_never_forwards(self):
        with patch.object(req, 'reuse_unvouched', return_value=True):
            forward, sync, merge, act = self.runtime_inputs(('success',) * 5)
        self.assertNotEqual('forward', act.call_args.args[1]['kind'])
        sync.assert_not_called()

    def test_open_github_pull_only_fast_forwards_to_the_new_commit(self):
        pull = {'number': 4, 'head': {'sha': 'o' * 40}, 'html_url': 'https://github.com/x/pull/4'}
        for ancestor, pushes in ((0, 1), (1, 0)):
            def git(*args, check=True):
                if args[0] == 'merge-base':
                    return type('Done', (), {'returncode': ancestor})()
                return 'tree'
            with (patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}),
                  patch.object(control, 'git', side_effect=git), patch.object(control, 'pages', return_value=[]),
                  patch.object(req, 'pull_for', return_value={'number': '12'}),
                  patch.object(control, 'api', return_value={'object': {'sha': 'm' * 40}}) as api,
                  patch.object(req, 'push_github') as push, patch.object(control, 'comment'),
                  patch.object(req, 'settle') as settle):
                req.advance(self.issue, '9', 'n' * 40, pull)
            self.assertEqual(pushes, push.call_count)
            self.assertEqual(pushes, settle.call_count)
            if pushes:
                self.assertEqual('PATCH', api.call_args.args[1])
                self.assertIn('n' * 40, api.call_args.args[2]['body'])
        with patch.object(control, 'git') as git:
            req.advance(self.issue, '9', 'o' * 40, pull)
            git.assert_not_called()

    def test_the_gate_row_never_decides_green_only_ci_and_the_review_do(self):
        five = ('success',) * 5
        # Whatever the gate reports, or if it never reported, a passed review over green CI is green.
        for gate in (None, 'pending', 'error', 'failure', 'success'):
            self.assertEqual((True, False), real_check_state(ci_checks(five, gate=gate)), gate)
        self.assertEqual((False, False), real_check_state(ci_checks(five, gate='error'), verdicts=('pass',)))
        self.assertEqual((False, True), real_check_state(ci_checks(five, gate='success'), verdicts=('pass', 'block')))
        self.assertEqual((False, False), real_check_state(ci_checks(five[:4] + ('pending',), gate='error')))
        self.assertEqual((False, True), real_check_state(ci_checks(five[:4] + ('failure',), gate='error')))
        with patch.object(control, 'api', return_value=ci_checks(five, gate='error')), \
                patch.object(reviews, 'api') as review:
            self.assertEqual((False, False), req.check_state('5'))
            review.assert_not_called()

    def test_forwarded_pull_merges_once_github_settles(self):
        states = iter([{'mergeable_state': 'unknown'}, {'mergeable_state': 'unstable'}, {'merged': True}])
        with (patch.object(control, 'api', side_effect=lambda url: next(states)),
              patch.object(req, 'merge_ready') as merge):
            self.assertTrue(req.merge_when_settled('7', attempts=5, pause=0))
        merge.assert_called_once()
        states = iter([{'mergeable_state': 'blocked'}, {'merged': False}])
        with patch.object(control, 'api', side_effect=lambda url: next(states)), patch.object(req, 'merge_ready'):
            self.assertFalse(req.merge_when_settled('7', attempts=1, pause=0))

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

    def test_first_dispatch_names_the_issue_head_and_checks(self):
        text = self.decide()['instruction']
        self.assertIn('需求 Issue #9', text)
        self.assertIn('不要 sleep', text)
        self.assertIn('FlClash-Actor: npc/开发助手', text)
        self.assertIn('tool/hooks/comment_density.sh', text)
        self.assertNotIn('立刻开 CNB PR', text)
        self.assertIn('远端分支头：不存在（首次派发）', text)

    def test_a_dispatch_with_a_known_head_names_the_sha_not_the_tree(self):
        comments = [self.marker('dev', 60, '', '2026-09-22T02:00:00Z')]
        rows = [self.attempt('error', '2026-09-22T02:00:00Z')]
        text = self.decide(comments, rows, tree='abc', sha='c' * 40)['instruction']
        self.assertIn('远端分支头：`' + 'c' * 40 + '`', text)
        self.assertNotIn('从已有提交', text)
        self.assertNotIn('分支头：`abc`', text)

    def test_unsigned_runs_do_not_open_a_pr_or_raise_the_rung(self):
        started = '2026-09-22T02:00:00Z'
        comments = [self.marker('dev', 60, '', started), {
            'created_at': '2026-09-22T02:05:00Z', 'body': '提交 SHA 已满足验收',
            'author': {'username': '507space/FlClash-alpha(开发助手)', 'is_npc': True}, 'signed': False}]
        unsigned = [dict(self.attempt('success', started), signed=False)]
        self.assertNotEqual('open-pr', self.decide(comments, unsigned, tree='abc')['kind'])
        self.assertEqual('wait', self.decide(comments, [dict(self.attempt('pending', started), signed=False)])['kind'])

    def test_attempts_reports_whether_the_dispatch_was_signed(self):
        statuses = {'npc': [{'context': {'npc.slug': req.POLICY['cnb'], 'npc.name': '开发助手', 'sn': 'cnb-a-1'},
                             'statuses': [{'state': 'pending'}]}]}
        signed = dict(self.marker('dev', 60, '', '2026-09-22T02:00:00Z'), statuses=statuses)
        unsigned = {'created_at': '2026-09-22T02:00:00Z', 'body': '随便 @ 一下', 'statuses': statuses}
        rows = req.attempts([signed, unsigned])
        self.assertEqual([True, False], [row['signed'] for row in rows])

    def test_a_hung_development_run_reports_overrun_once(self):
        started = '2026-09-22T00:40:00Z'
        comments = [self.marker('dev', 60, '', started)]
        rows = [self.attempt('pending', started)]
        action = self.decide(comments, rows)
        self.assertEqual(('overrun', 'cnb-test-1', 140), (action['kind'], action['sn'], action['minutes']))
        notes = [{'created_at': '2026-09-22T02:50:00Z', 'body': req.OVERRUN.format('cnb-test-1')}]
        self.assertEqual('wait', self.decide(comments + notes, rows)['kind'])
        self.assertEqual('wait', self.decide(comments, [self.attempt('pending', '2026-09-22T02:30:00Z')])['kind'])

    def test_overrun_is_posted_without_a_signature(self):
        with patch.object(control, 'comment') as note:
            req.act(self.issue, {'kind': 'overrun', 'sn': 'cnb-a-1', 'minutes': 95}, '')
        body = note.call_args.args[1]
        self.assertTrue(body.startswith(req.OVERRUN.format('cnb-a-1')))
        self.assertIn('约 95 分钟', body)
        self.assertNotIn('<!-- flclash-requirement {', body)

    def test_owner_hold_pauses_and_release_resumes(self):
        owner = {'username': 'Aharon', 'is_npc': False}
        npc = {'username': 'Aharon', 'is_npc': True}
        visitor = {'username': 'visitor', 'is_npc': False}
        hold = {'created_at': '2026-09-22T02:00:00Z', 'body': 'HOLD', 'author': owner}
        release = {'created_at': '2026-09-22T02:10:00Z', 'body': ' RELEASE\n', 'author': owner}
        self.assertEqual('HOLD', pause.command(hold))
        self.assertEqual('2026-09-22T02:00:00Z', pause.held([hold]))
        self.assertEqual('', pause.held([hold, release]))
        self.assertEqual('', pause.held([release]))
        for body, author in (('HOLD', npc), ('HOLD', visitor), ('HOLD 一下', owner), ('hold', owner)):
            self.assertEqual('', pause.command({'body': body, 'author': author}), body)
            self.assertEqual('', pause.held([{'created_at': 'x', 'body': body, 'author': author}]))
        expected = {'source': 'hold', 'head': '', 'ref': 'automation/req-9',
                    'since': '2026-09-22T02:00:00Z', 'branch': 'automation/req-9'}
        self.assertEqual(expected, pause.paused('branch', 'automation/req-9', [hold]))
        self.assertEqual(expected, pause.paused('main', 'automation/req-9', [hold]))
        self.assertIsNone(pause.paused('branch', 'automation/req-9', [hold, release]))
        self.assertIsNone(pause.paused('branch', 'automation/security-sync-x', [hold]))
        with patch.object(pause, 'pages', return_value=[hold]) as pages:
            self.assertEqual('hold', pause.paused('branch', 'automation/req-9', None)['source'])
        self.assertIn('/issues/9/comments', pages.call_args.args[0])
        with self.assertRaises(ValueError):
            pause.paused('x', 'automation/req-9', [hold])

    def test_hold_wins_over_green_checks_until_the_notice_is_posted(self):
        self.assertEqual({'kind': 'hold', 'ref': '2026-09-22T02:00:00Z', 'sn': ''},
                         self.decide(hold='2026-09-22T02:00:00Z'))
        notice = {'created_at': '2026-09-22T02:05:00Z', 'body': req.HOLD_MARKER.format('2026-09-22T02:00:00Z')}
        self.assertEqual('wait', self.decide([notice], hold='2026-09-22T02:00:00Z')['kind'])
        self.assertEqual('wait', self.decide([notice], tree='abc', hold='2026-09-22T02:00:00Z',
                                             checks_green=True, behind=True)['kind'])
        self.assertEqual('sync-main', self.decide([notice], tree='abc', checks_green=True,
                                                  behind=True)['kind'])
        started = '2026-09-22T02:00:00Z'
        rows = [self.attempt('pending', started), self.attempt('success', started, role='审查助手', sn='cnb-a-2')]
        self.assertEqual('cnb-test-1', req.decide(
            self.issue, [], rows, '', False, False, False, '', self.now, hold=started)['sn'])

    def test_hold_notice_starts_with_its_marker_and_is_never_a_bare_hold_word(self):
        with patch.object(control, 'comment') as note:
            req.act(self.issue, {'kind': 'hold', 'ref': '2026-09-22T02:00:00Z', 'sn': ''}, 's' * 40)
        body = note.call_args.args[1]
        self.assertTrue(body.startswith(req.HOLD_MARKER.format('2026-09-22T02:00:00Z')))
        self.assertIn('automation/req-9', body)
        self.assertNotIn('flclash-requirement {', body)
        self.assertNotIn('仍在运行', body)
        self.assertNotIn('草稿', body)
        self.assertIn('合并', body)
        self.assertNotIn(body.strip(), ('HOLD', 'RELEASE'))
        with patch.object(control, 'comment') as note:
            req.act(self.issue, {'kind': 'hold', 'ref': '2026-09-22T02:00:00Z', 'sn': 'cnb-a-1'}, 's' * 40)
        self.assertIn('`cnb-a-1` 仍在运行', note.call_args.args[1])

    def test_dispatch_payload_names_the_branch_head(self):
        with patch.object(control, 'comment') as note:
            req.act(self.issue, self.decide(sha='d' * 40), 'd' * 40)
        self.assertIn('"head": "' + 'd' * 40 + '"', note.call_args.args[1])

    def test_foreign_commits_ignore_agent_commits_and_side_branches(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(control, 'ROOT', pathlib.Path(directory)), patch.object(control, 'git', side_effect=local_git):
            control.git('init')
            control.git('config', 'user.name', 'controller')
            control.git('config', 'user.email', 'test@example.invalid')
            control.git('config', 'commit.gpgsign', 'false')
            control.git('commit', '--allow-empty', '-m', 'chore: base', '-m', 'FlClash-Actor: controller')
            since = control.git('rev-parse', 'HEAD')
            control.git('commit', '--allow-empty', '-m', 'feat: agent work', '-m', 'FlClash-Actor: npc/开发助手')
            control.git('commit', '--allow-empty', '-m', 'fix: hand written',
                        '--author', 'Owner <owner@example.invalid>')
            head = control.git('rev-parse', 'HEAD')
            side = control.git('commit-tree', control.git('rev-parse', 'HEAD^{tree}'), '-p', head,
                               '-m', 'fix: side work')
            merge = control.git('commit-tree', control.git('rev-parse', 'HEAD^{tree}'), '-p', head, '-p', side,
                                '-m', 'Merge branch side', '-m', 'FlClash-Actor: controller')
            self.assertEqual([], req.foreign_commits('', head))
            self.assertEqual([], req.foreign_commits(head, head))
            found = req.foreign_commits(since, merge)
            self.assertEqual(['fix: hand written'], [item[2] for item in found])
            self.assertEqual('Owner', found[0][1])
            self.assertRegex(found[0][0], r'^[0-9a-f]{40}$')
        self.assertEqual([], req.foreign_commits('x' * 40, 'y' * 40))
        empty = type('Done', (), {'returncode': 0, 'stdout': ''})()
        failure = type('Done', (), {'returncode': 128, 'stdout': ''})()
        with patch.object(control, 'git', side_effect=[empty, failure]):
            with patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual([], req.foreign_commits('a' * 40, 'b' * 40))
        self.assertEqual('cannot list commits aaaaaaaaaaaa..bbbbbbbbbbbb; origin report skipped',
                         out.getvalue().strip())

    def test_mirror_body_lists_origins_before_the_signature_marker(self):
        payload = {'base': 'a' * 40, 'head': 'b' * 40, 'tree': 'c' * 40, 'cnb_number': '3',
                   'branch': 'automation/req-9'}
        result = type('Done', (), {'returncode': 0, 'stdout': (
            'a' * 40 + '\x1fNPC\x1ffeat: <!-- flclash-security-mirror {} -->\x1fnpc/开发助手\x1e'
            + 'b' * 40 + '\x1fOwner\x1ffeat: work\x1f<!-- flclash-security-mirror {} -->\x1e')})()
        with patch.object(control, 'git', return_value=result):
            rows = req.origin_rows('a' * 40, 'b' * 40)
        body = req.mirror_body(payload, rows)
        self.assertIn('**提交归属**', body)
        self.assertIn(rows[0], body)
        self.assertNotIn('<!-- flclash-security-mirror {}', body)
        self.assertEqual(1, body.count('<!-- flclash-security-mirror '))
        self.assertLess(body.index('**提交归属**'), body.index('<!-- flclash-security-mirror '))
        self.assertEqual(payload, security_finish.mirror_record({'body': body}))
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            sealed = req.markers([{'body': req.envelope(payload), 'created_at': '2026-09-22T01:00:00Z'}])[0]
        self.assertEqual(payload, {key: sealed[key] for key in payload})
        self.assertNotIn('**提交归属**', req.mirror_body(payload))

    def test_origin_rows_name_the_actor_or_the_author(self):
        marker = '<!-- flclash-security-mirror {"payload": {"head": "' + 'c' * 40 + '"}, "signature": "x"} -->'
        result = type('Done', (), {'returncode': 0, 'stdout': (
            'a' * 40 + '\x1fNPC\x1ffeat: one\x1fnpc/开发助手\x1e'
            + 'b' * 40 + '\x1fOwner\x1ffix: <two> ' + marker + '\x1f\x1e')})()

        def git(*args, check=True):
            if args[0] == 'fetch':
                self.assertIn('a' * 40, args)
                return type('Done', (), {'returncode': 0, 'stdout': ''})()
            self.assertEqual('log', args[0])
            self.assertEqual('--first-parent', args[1])
            self.assertIn('--max-count=20', args)
            self.assertEqual('a' * 40 + '..' + 'b' * 40, args[-1])
            return result
        with patch.object(control, 'git', side_effect=git) as calls:
            rows = req.origin_rows('a' * 40, 'b' * 40)
            self.assertEqual('fetch', calls.call_args_list[0].args[0])
        self.assertEqual(['- `aaaaaaaa` 归属：npc/开发助手：feat: one',
                          '- `bbbbbbbb` 归属：人工（无 FlClash-Actor，作者 Owner）：fix: &lt;two> &lt;!-- '
                          'flclash-security-mirror {"payload": {"head": "cccccccccccccccccc'], rows)
        actor = type('Done', (), {'returncode': 0, 'stdout': (
            'c' * 40 + '\x1f<Owner>\x1f' + marker + '\x1fnpc/<开发助手>\x1e')})()
        with patch.object(control, 'git', return_value=actor):
            named = req.origin_rows('a' * 40, 'b' * 40)
        self.assertIn('&lt;开发助手>', named[0])
        self.assertNotIn('<', named[0].replace('&lt;', ''))
        self.assertIn('：&lt;!-- flclash-security-mirror {"payload": {"head": "cccccccccccccccccc', named[0])
        self.assertEqual(1, named[0].count('&lt;!--'))
        payload = {'base': 'a' * 40, 'head': 'c' * 40, 'tree': 'd' * 40, 'cnb_number': '3',
                   'branch': 'automation/req-9'}
        body = req.mirror_body(payload, rows)
        self.assertEqual(1, body.count('<!-- flclash-security-mirror'))
        self.assertEqual(payload, security_finish.mirror_record({'body': body}))
        failure = type('Done', (), {'returncode': 1, 'stdout': ''})()
        with patch.object(control, 'git', side_effect=[type('Done', (), {'returncode': 0, 'stdout': ''})(), failure]):
            with patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual([], req.origin_rows('a' * 40, 'b' * 40))
            self.assertEqual('cannot list commits aaaaaaaaaaaa..bbbbbbbbbbbb; origin report skipped',
                             out.getvalue().strip())
        with patch.object(control, 'git') as git:
            self.assertEqual([], req.origin_rows('', 'b' * 40))
            git.assert_not_called()

    def test_reconcile_tells_a_dispatch_about_foreign_commits(self):
        issue = {'number': '9', 'title': '[需求] 导出', 'state': 'open', 'body': BODY,
                 'author': {'username': 'Aharon', 'is_npc': False}}
        owner = {'username': 'Aharon', 'is_npc': False}
        foreign = [('f' * 40, 'Owner', 'fix: hand')]

        def pages(url, held):
            if url.endswith('/issues?state=open'):
                return [issue]
            if url.endswith('/pulls?state=all'):
                return []
            return [{'created_at': '2026-09-22T02:20:00Z', 'body': 'HOLD', 'author': owner}] if held else []
        for held, expected in ((False, 1), (True, 0)):
            posted = []
            reply = lambda url: issue if url.endswith('/issues/9') else {'object': {'sha': 'a' * 40}}
            with (patch.object(control, 'pages', side_effect=lambda url, _held=held: pages(url, _held)),
                  patch.object(control, 'api', side_effect=reply),
                  patch.object(req, 'branch_sha', return_value='b' * 40),
                  patch.object(control, 'git', return_value='tree'),
                  patch.object(req, 'contained', return_value=False),
                  patch.object(req, 'check_state', return_value=(False, False)),
                  patch.object(req, 'foreign_commits', return_value=foreign) as commits,
                  patch.object(control, 'comment', side_effect=lambda *args: posted.append(args[1]))):
                req.reconcile()
            self.assertEqual(expected, commits.call_count)
            if held:
                self.assertNotIn('flclash-requirement {', posted[0])
            else:
                self.assertEqual('a' * 40, commits.call_args.args[0])
                self.assertIn('分支上有不是开发助手推的提交：ffffffff Owner fix: hand', posted[0])

    def test_dispatch_start_prefers_the_last_signed_dispatch_head(self):
        marks = [{'issue': '9', 'phase': 'dev', 'head': 'c' * 40}, {'issue': '9', 'phase': 'retry', 'head': 'd' * 40},
                 {'issue': '9', 'phase': 'dev', 'head': 'e' * 40}]
        self.assertEqual('e' * 40, req.dispatch_start(marks, 'e' * 40))
        self.assertEqual('d' * 40, req.dispatch_start(marks[:2] + [{'phase': 'dev', 'head': 'short'}], 'e' * 40))
        self.assertEqual('c' * 40, req.dispatch_start(marks[:1] + [{'phase': 'dev', 'head': 'n' * 39}], 'e' * 40))
        with patch.object(control, 'api', return_value={'object': {'sha': 'a' * 40}}) as main:
            self.assertEqual('a' * 40, req.dispatch_start([], 'e' * 40))
            self.assertEqual('a' * 40, req.dispatch_start(
                [{'issue': '9', 'phase': 'dev', 'head': 'short'}], 'e' * 40))
            self.assertEqual(2, main.call_count)

    def test_an_unescaped_mirror_marker_in_an_author_name_stays_inside_the_quote(self):
        raw = '<!-- flclash-security-mirror {"payload": {"head": "' + 'c' * 40 + '"}, "signature": "x"} -->'
        result = type('Done', (), {'returncode': 0, 'stdout': (
            'b' * 40 + '\x1fOwner ' + raw + '\x1fgit log --format=%an \x1f\x1e')})()
        with patch.object(control, 'git', return_value=result):
            rows = req.origin_rows('a' * 40, 'b' * 40)
        payload = {'base': 'a' * 40, 'head': 'b' * 40, 'tree': 'd' * 40, 'cnb_number': '3',
                   'branch': 'automation/req-9'}
        body = req.mirror_body(payload, rows)
        self.assertEqual(1, body.count('<!--'))
        self.assertEqual(payload, security_finish.mirror_record({'body': body}))
        self.assertIn('&lt;!-- flclash-security-mirror', body)

    def test_a_hold_on_the_running_dispatch_waits_instead_of_forwarding(self):
        started = '2026-09-22T02:00:00Z'
        owner = {'username': req.POLICY['approver'], 'is_npc': False}
        comments = [self.marker('dev', 60, 'abc', started),
                    {'created_at': '2026-09-22T02:30:00Z', 'body': 'HOLD', 'author': owner}]
        rows = [self.attempt('success', started)]
        notice = {'created_at': '2026-09-22T02:35:00Z', 'body': req.HOLD_MARKER.format(started)}
        self.assertEqual('wait', self.decide(comments + [notice], rows, tree='abc', checks_green=True,
                                             hold=started)['kind'])
        self.assertEqual('hold', self.decide(comments, rows, tree='abc', checks_green=True, hold=started)['kind'])
        self.assertEqual('forward', self.decide(comments, rows, tree='abc', checks_green=True)['kind'])
        with patch.object(control, 'comment') as note:
            req.act(self.issue, {'kind': 'hold', 'ref': started, 'sn': 'cnb-test-1'}, 'abc')
        self.assertIn('`cnb-test-1` 仍在运行', note.call_args.args[1])
        self.assertNotIn('草稿', note.call_args.args[1])

    def env_marker(self, phase, head, at='2026-09-22T02:10:00Z'):
        payload = {'issue': '9', 'phase': phase, 'head': head, 'sn': 'cnb-retry-1'}
        return {'created_at': at, 'body': req.envelope(payload)}

    def env_pull(self, head='b' * 40):
        return {'number': 4, 'head': {'sha': head, 'ref': 'refs/heads/automation/req-9'}}

    def env_statuses(self, state='error', name=req.DEPENDENCY_GATE, sn='cnb-ud2-1k64u0imv'):
        return {'statuses': [{'state': state, 'context': f'cnb({name})',
                              'target_url': f'https://cnb.cool/507space/FlClash-alpha/-/build/logs/{sn}'}]}

    def test_a_first_environment_failure_retries_with_an_empty_commit(self):
        head = 'b' * 40
        self.assertEqual('env-retry', self.decide(env_failure={'kind': 'osv-unreachable', 'sha': head,
                                                               'sn': 'cnb-ud2-1k64u0imv'})['kind'])
        calls = []

        def git(*args, check=True):
            calls.append(args)
            return type('Done', (), {'returncode': 0, 'stdout': 'c' * 40 + '\n'})()
        with patch.object(control, 'git', side_effect=git), patch.object(control, 'sync_branch', return_value=0) as push, \
                patch.object(control, 'comment') as note:
            req.act(self.issue, {'kind': 'env-retry', 'head': head, 'sn': 'cnb-ud2-1k64u0imv', 'count': 1}, head)
        self.assertEqual(('commit-tree', head + '^{tree}', '-p', head,
                          '-m', 'Retry dependency rescan after environment failure',
                          '-m', 'FlClash-Actor: controller'), calls[0])
        self.assertEqual(('automation/req-9', 'c' * 40), push.call_args.args)
        body = note.call_args.args[1]
        self.assertIn('这是第 1/2 次自动重跑', body)
        self.assertIn('`' + 'b' * 12 + '`', body)
        self.assertIn('build/logs/cnb-ud2-1k64u0imv', body)
        self.assertIn('"phase": "env-retry"', body)

    def test_a_commit_that_never_reached_the_branch_blocks_the_retry(self):
        head = 'b' * 40
        with patch.object(control, 'git', return_value=type('Done', (), {'returncode': 128, 'stdout': ''})()), \
                patch.object(control, 'sync_branch') as push, patch.object(control, 'comment') as note:
            req.act(self.issue, {'kind': 'env-retry', 'head': head, 'sn': 'cnb-ud2-1k64u0imv', 'count': 1}, head)
        push.assert_not_called()
        self.assertIn('"phase": "env-blocked"', note.call_args.args[1])
        self.assertIn('没有放行', note.call_args.args[1])

    def test_a_head_that_already_has_an_environment_marker_waits(self):
        head = 'b' * 40
        failure = {'kind': 'osv-unreachable', 'sha': head, 'sn': 'cnb-ud2-1k64u0imv'}
        comments = [self.env_marker('env-retry', head)]
        with patch.object(control, 'comment') as note:
            self.assertEqual('wait', self.decide(comments, env_failure=failure)['kind'])
        note.assert_not_called()
        with patch.object(control, 'git') as git, patch.object(control, 'sync_branch') as push:
            req.act(self.issue, {'kind': 'wait'}, head)
        git.assert_not_called()
        push.assert_not_called()

    def test_the_second_retry_on_the_same_head_blocks_and_the_owner_is_told_once(self):
        head = 'b' * 40
        comments = [self.env_marker('env-retry', 'd' * 40, '2026-09-22T02:05:00Z'),
                    self.env_marker('env-retry', 'e' * 40)]
        failure = {'kind': 'osv-unreachable', 'sha': head, 'sn': 'cnb-ud2-1k64u0imv'}
        posted = []
        with patch.object(control, 'comment', side_effect=lambda *args: posted.append(args[1])):
            self.assertEqual('wait', self.decide(comments, env_failure=failure)['kind'])
        self.assertEqual(1, len(posted))
        self.assertIn('api.osv.dev', posted[0])
        self.assertIn('没有放行', posted[0])
        self.assertIn('"phase": "env-blocked"', posted[0])
        self.assertIn('"head": "' + head + '"', posted[0])
        blocked = [self.env_marker('env-blocked', head)]
        with patch.object(control, 'comment') as note:
            self.assertEqual('wait', self.decide(comments + blocked, env_failure=failure)['kind'])
        note.assert_not_called()

    def test_a_failure_without_the_marker_is_an_ordinary_failure(self):
        statuses = self.env_statuses()['statuses']
        pull = self.env_pull('b' * 40)
        with patch.object(req, 'build_log', return_value='no marker at all\n'):
            self.assertIsNone(req.unreachable(pull, statuses))
        for error in (RuntimeError('CNB is down'), KeyError('pipelines'), ValueError('bad json')):
            with patch.object(control, 'api', side_effect=error):
                self.assertIsNone(req.unreachable(pull, statuses))
            with patch.object(req, 'build_log', side_effect=error):
                self.assertIsNone(req.unreachable(pull, statuses))
        # Without a marker the ladder behaves exactly as it did before.
        started = '2026-09-22T02:00:00Z'
        dispatch = self.marker('dev', 60, 'tree-1', started)
        rows = [self.attempt('failure', started)]
        self.assertEqual(self.decide([dispatch], rows, tree='tree-1'),
                         self.decide([dispatch], rows, tree='tree-1', env_failure=None))
        self.assertEqual('retry', self.decide([dispatch], rows, tree='tree-1')['phase'])

    def test_a_red_paired_review_gate_is_not_only_an_environment_failure(self):
        # The pull request status list carries the review gate next to CI; a red gate
        # is a review verdict, not an unreachable advisory source.
        statuses = self.env_statuses()['statuses'] + [
            {'state': 'failure', 'context': 'cnb(' + req.REVIEW_GATE + ')',
             'target_url': 'https://cnb.cool/x/-/reviews'}]
        with patch.object(req, 'build_log') as log:
            self.assertIsNone(req.unreachable(self.env_pull(), statuses))
        log.assert_not_called()
        with patch.object(req, 'build_log', return_value=''):
            self.assertIsNone(req.unreachable(self.env_pull(), self.env_statuses('success')['statuses']))

    def test_more_than_one_red_check_is_not_an_environment_failure(self):
        statuses = self.env_statuses()['statuses'] + [{'state': 'failure', 'context': 'cnb(Automation unit tests)',
                                                      'target_url': 'https://cnb.cool/x/-/build/logs/cnb-a-1'}]
        with patch.object(req, 'build_log') as log:
            self.assertIsNone(req.unreachable(self.env_pull(), statuses))
        log.assert_not_called()
        statuses = [{'state': 'error', 'context': 'cnb(Automation unit tests)',
                     'target_url': 'https://cnb.cool/x/-/build/logs/cnb-a-1'}]
        with patch.object(req, 'build_log') as log:
            self.assertIsNone(req.unreachable(self.env_pull(), statuses))
        log.assert_not_called()

    def test_a_marker_for_another_head_is_not_an_environment_failure(self):
        pull = self.env_pull('b' * 40)
        line = env_failure.line('osv-unreachable', sha='f' * 40)
        with patch.object(req, 'build_log', return_value='stage log\n' + line + '\n'):
            self.assertIsNone(req.unreachable(pull, self.env_statuses()['statuses']))
        mine = env_failure.line('osv-unreachable', sha='b' * 40)
        with patch.object(req, 'build_log', return_value='stage log\n' + mine + '\n'):
            self.assertEqual({'kind': 'osv-unreachable', 'sha': 'b' * 40, 'sn': 'cnb-ud2-1k64u0imv'},
                             req.unreachable(pull, self.env_statuses()['statuses']))

    def test_the_rescan_stage_log_is_read_from_the_build_status(self):
        status = {'pipelines': {'cnb-ud2-1k64u0imv-001': {
            'id': 'cnb-ud2-1k64u0imv-001', 'name': 'Go dependency regression tests',
            'stages': [{'id': 'stage-0', 'name': 'Verify core with resolved dependencies'},
                       {'id': 'stage-1',
                        'name': 'Rescan actual versions and verify repaired dependency'}]}}}
        urls = []

        def api(url, missing=False):
            urls.append(url)
            return status if '/build/status/' in url else env_failure.line('osv-unreachable', sha='b' * 40)
        with patch.object(control, 'api', side_effect=api):
            self.assertIn('osv-unreachable', req.build_log('cnb-ud2-1k64u0imv'))
        self.assertEqual(['https://api.cnb.cool/507space/FlClash-alpha/-/build/status/cnb-ud2-1k64u0imv',
                          'https://api.cnb.cool/507space/FlClash-alpha/-/build/logs/stage/cnb-ud2-1k64u0imv/'
                          'cnb-ud2-1k64u0imv-001/stage-1'], urls)
        with patch.object(control, 'api', return_value={'pipelines': {}}):
            self.assertEqual('', req.build_log('cnb-ud2-1k64u0imv'))
        with patch.object(control, 'api', return_value=None):
            self.assertEqual('', req.build_log('cnb-ud2-1k64u0imv'))

    def test_reconcile_asks_for_the_statuses_of_the_pull_number(self):
        self.issue['author'] = {'username': 'Aharon', 'is_npc': False}
        pull = {'number': 4, 'head': {'sha': 'b' * 40, 'ref': 'refs/heads/automation/req-9'},
                'base': {'sha': 'm' * 40}, 'state': 'open'}
        asked = []

        def api(url, method='GET', data=None, missing=False, timeout=60):
            asked.append(url)
            path = url.split(control.POLICY['cnb'] + '/-/')[-1].split('?')[0]
            if path == 'issues' and 'state=open' in url:
                return [{'number': '9'}]
            if path == 'issues/9':
                return dict(self.issue)
            if path == 'issues/9/comments':
                return []
            if path == 'pulls' and 'state=all' in url:
                return [dict(pull, head={**pull['head'], 'repo': {'path': '507space/FlClash-alpha'}},
                             state='open')]
            if path == 'pulls/4':
                return pull
            if path == 'pulls/4/comments':
                return []
            if '/commit-statuses' in url:
                return self.env_statuses()
            if url.startswith('https://api.github.com/') and url.endswith('/git/ref/heads/main'):
                return {'object': {'sha': 'm' * 40}}
            raise AssertionError(url)
        actions = []
        with patch.object(control, 'api', side_effect=api), patch.object(req, 'branch_sha', return_value='b' * 40), \
                patch.object(control, 'git', return_value=type('Done', (), {'returncode': 0, 'stdout': 'tree-1'})()), \
                patch.object(req, 'unreachable', return_value=None) as scan, \
                patch.object(req, 'review_block', return_value=(False, '')) as review, \
                patch.object(req, 'act', side_effect=lambda issue, action, sha: actions.append(action)):
            req.reconcile()
        self.assertEqual('https://api.cnb.cool/507space/FlClash-alpha/-/pulls/4/commit-statuses',
                         [url for url in asked if '/commit-statuses' in url][0])
        self.assertEqual(4, scan.call_args.args[0]['number'])
        self.assertEqual(4, review.call_args.args[0]['number'])
        self.assertIn('error', [item['state'] for item in scan.call_args.args[1]])

    def test_an_environment_marker_does_not_move_the_development_ladder(self):
        head = 'b' * 40
        started = '2026-09-22T02:00:00Z'
        dispatch = self.marker('dev', 60, 'tree-1', started)
        failure = {'kind': 'osv-unreachable', 'sha': head, 'sn': 'cnb-ud2-1k64u0imv'}
        retried = [dispatch, self.env_marker('env-retry', head, '2026-09-22T02:05:00Z')]
        rows = [self.attempt('success', started)]
        with patch.object(control, 'comment'):
            self.assertEqual('wait', self.decide(retried, rows, tree='tree-1', env_failure=failure)['kind'])
            after = self.decide(retried, rows, tree='tree-1', review_failed=True, env_failure=failure)
        without = self.decide([dispatch], rows, tree='tree-1', review_failed=True)
        self.assertEqual('dispatch', after['kind'])
        self.assertEqual(without, after)

    def test_an_environment_failure_never_forwards_or_syncs(self):
        head = 'b' * 40
        failure = {'kind': 'osv-unreachable', 'sha': head, 'sn': 'cnb-ud2-1k64u0imv'}
        started = '2026-09-22T02:00:00Z'
        dispatch = self.marker('dev', 60, 'tree-1', started)
        rows = [self.attempt('success', started)]
        self.assertEqual('forward', self.decide([dispatch], rows, tree='tree-1', checks_green=True)['kind'])
        self.assertEqual('sync-main', self.decide([dispatch], rows, tree='tree-1', checks_green=True,
                                                  behind=True)['kind'])
        for action in (self.decide([dispatch], rows, tree='tree-1', has_pull=True, env_failure=failure),
                       self.decide([dispatch], rows, tree='tree-1', has_pull=True, env_failure=failure,
                                   hold=''),
                       self.decide([], rows, tree='tree-1', has_pull=True, env_failure=failure)):
            self.assertNotIn(action['kind'], ('forward', 'sync-main'), action)
        self.assertEqual('dispatch', self.decide([dispatch], rows, tree='tree-1', review_failed=True,
                                                 env_failure=failure)['kind'])
        self.assertEqual('sync-main', self.decide(checks_green=True, behind=True)['kind'])

    def test_a_blocked_review_still_gets_a_developer_after_an_environment_retry(self):
        head = 'b' * 40
        started = '2026-09-22T02:00:00Z'
        dispatch = self.marker('dev', 60, 'tree-1', started)
        comments = [dispatch, self.env_marker('env-retry', head, '2026-09-22T02:05:00Z')]
        rows = [self.attempt('success', started)]
        action = self.decide(comments, rows, tree='tree-1', review_failed=True, env_failure=None)
        self.assertEqual('dispatch', action['kind'])
        self.assertEqual(120, action['rung'])
