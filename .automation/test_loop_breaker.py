import datetime
import os
import pathlib
import unittest
from unittest.mock import patch

import control
import requirements as req


BODY = """## 要改什么

加快日志导出

## 验收标准

导出包含 coverage.txt

## 不做什么

不改节点

## 影响范围

Go core
"""

SN = 'cnb-test-1'
STATUS = {'pipelines': {'cnb-test-1-001': {'id': 'cnb-test-1-001', 'name': 'npc',
                                           'stages': [{'id': 'stage-0', 'name': 'NPC'}]}}}
# Every rule the developer prompt and the dispatch must both carry.
RULES = ('连续失败 3 次', '先提交', '失败用例名', '报错关键行', '假设', '【熔断】', '检查点',
         '25 次', '5 个', '每加一条跑一次', '一份需求只做一件事', '顺带修正')


def network(log):
    """Answer the two CNB requests the digest makes; `log` is the stage log body."""
    urls = []

    def api(url, method='GET', data=None, missing=False, timeout=60):
        urls.append(url)
        if url.endswith(f'/build/status/{SN}'):
            return STATUS
        if url.endswith(f'/build/logs/stage/{SN}/cnb-test-1-001/stage-0'):
            if isinstance(log, Exception):
                raise log
            return log
        raise AssertionError(f'unexpected request {method} {url}')
    return patch.object(control, 'api', side_effect=api), urls


class LoopBreakerTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)
        self.now = datetime.datetime.fromisoformat('2026-09-22T03:00:00+00:00')
        self.issue = {'number': '9', 'title': '[需求] 导出', 'state': 'open', 'body': BODY}
        self.scope = req.parse(BODY)['scope']

    def marker(self, phase, rung, tree, at):
        payload = {'issue': '9', 'scope': self.scope, 'phase': phase, 'rung': rung, 'tree': tree}
        return {'created_at': at, 'body': req.envelope(payload)}

    def attempt(self, state, at, role='开发助手', sn=SN):
        return {'at': at, 'state': state, 'detail': '', 'sn': sn, 'role': role}

    def report(self, body, at, role='开发助手'):
        return {'created_at': at, 'body': body,
                'author': {'username': f'{control.POLICY["cnb"]}({role})', 'is_npc': True}}

    def decide(self, comments, rows, tree='', **kwargs):
        return req.decide(self.issue, comments, rows, tree, False, kwargs.get('checks_green', False),
                          kwargs.get('review_failed', False), kwargs.get('review_text', ''), self.now,
                          has_pull=kwargs.get('has_pull', False), behind=kwargs.get('behind', False))

    def test_the_dispatch_carries_the_counted_breaker_rules(self):
        parsed = dict(req.parse(BODY), number='9')
        text = req.instruction(parsed, 60, 'dev', '', '', '', '')
        for rule in RULES:
            self.assertIn(rule, text)

    def test_the_developer_role_carries_the_same_rules(self):
        settings = (pathlib.Path(__file__).resolve().parent.parent / '.cnb' / 'settings.yml').read_text()
        role = settings.split('- name: 开发助手', 1)[1].split('- name: 审查助手', 1)[0]
        for rule in RULES:
            self.assertIn(rule, role)

    def test_a_breaker_report_hands_the_round_to_diagnose(self):
        comments = [self.marker('dev', 60, '', '2026-09-22T02:00:00Z'),
                    self.report('【熔断】\n失败用例：export_test 第 3 次失败', '2026-09-22T02:30:00Z')]
        rows = [self.attempt('success', '2026-09-22T02:00:00Z')]
        action = self.decide(comments, rows, tree='tree-1')
        self.assertEqual(('diagnose', '审查助手'), (action['phase'], action['role']))
        self.assertIn('export_test 第 3 次失败', action['instruction'])
        # A failed review must not pull a breaker round back to the developer either.
        action = self.decide(comments, rows, tree='tree-1', review_failed=True, review_text='CI 未通过', has_pull=True)
        self.assertEqual('diagnose', action['phase'])

    def test_breakers_stop_cycling_through_diagnose(self):
        comments = []
        for minute, phase in ((0, 'diagnose'), (10, 'diagnose'), (20, 'diagnose'), (30, 'targeted')):
            comments.append(self.marker(phase, 60, f'tree-{minute}', f'2026-09-22T02:{minute:02d}:00Z'))
        comments.append(self.report('【熔断】', '2026-09-22T02:35:00Z'))
        rows = [self.attempt('success', '2026-09-22T02:30:00Z')]
        self.assertNotEqual('diagnose', self.decide(comments, rows, tree='tree-9').get('phase'))

    def test_green_checks_never_forward_an_unhandled_breaker(self):
        comments = [self.marker('dev', 60, '', '2026-09-22T02:00:00Z'),
                    self.report('阶段评论：export_test 未改完', '2026-09-22T02:20:00Z'),
                    self.report('【熔断】\nexport_test 连续失败 3 次', '2026-09-22T02:30:00Z')]
        rows = [self.attempt('success', '2026-09-22T02:00:00Z')]
        for behind in (False, True):
            action = self.decide(comments, rows, tree='tree-1', checks_green=True, has_pull=True, behind=behind)
            self.assertEqual(('dispatch', 'diagnose'), (action['kind'], action.get('phase')))
            self.assertIn('export_test 连续失败 3 次', action['instruction'])
        # While that diagnose runs or answers, green checks still wait for the developer's next round.
        comments.append(self.marker('diagnose', 60, 'tree-1', '2026-09-22T02:40:00Z'))
        rows.append(self.attempt('running', '2026-09-22T02:40:00Z', role='审查助手', sn='cnb-review-2'))
        self.assertEqual('wait', self.decide(comments, rows, tree='tree-1', checks_green=True, has_pull=True)['kind'])

    def test_a_breaker_past_the_diagnose_cap_stops_instead_of_forwarding(self):
        comments = [self.marker(phase, 60, f'tree-{minute}', f'2026-09-22T02:{minute:02d}:00Z')
                    for minute, phase in ((0, 'diagnose'), (10, 'diagnose'), (20, 'diagnose'), (30, 'targeted'))]
        comments.append(self.report('【熔断】', '2026-09-22T02:35:00Z'))
        rows = [self.attempt('success', '2026-09-22T02:30:00Z')]
        action = self.decide(comments, rows, tree='tree-9', checks_green=True, has_pull=True)
        self.assertEqual(('stop', 'stuck'), (action['kind'], action.get('phase')))
        self.assertIn('owner', action['body'])
        comments.append(self.marker('stuck', 60, 'tree-9', '2026-09-22T02:40:00Z'))
        self.assertEqual('wait', self.decide(comments, rows, tree='tree-9', checks_green=True, has_pull=True)['kind'])

    def test_a_new_developer_round_without_a_breaker_forwards_green_checks(self):
        comments = [self.marker('dev', 60, '', '2026-09-22T02:00:00Z'),
                    self.report('【熔断】', '2026-09-22T02:30:00Z'),
                    self.marker('targeted', 60, 'tree-1', '2026-09-22T02:50:00Z'),
                    self.report('验收条目全部转绿', '2026-09-22T03:00:00Z')]
        rows = [self.attempt('success', '2026-09-22T02:50:00Z')]
        self.assertEqual('forward', self.decide(comments, rows, tree='tree-2', checks_green=True, has_pull=True)['kind'])
        self.assertEqual('sync-main', self.decide(comments, rows, tree='tree-2', checks_green=True, has_pull=True,
                                                  behind=True)['kind'])

    def test_the_digest_keeps_the_tail_and_the_failure_lines(self):
        lines = ['Traceback (most recent call last):', 'step FAILED: export_test'] + [
            f'line {i}' for i in range(100)] + ['run aborted after 240 turns']
        patcher, urls = network({'code': 0, 'data': {'content': lines}})
        with patcher:
            digest = req.log_digest(SN)
        for wanted in ('Traceback', 'FAILED: export_test', 'line 99', 'line 62', 'aborted after 240'):
            self.assertIn(wanted, digest)
        self.assertNotIn('line 10\n', digest)
        self.assertEqual(2, len(urls))

    def test_the_digest_reads_a_string_body_is_bounded_and_redacted(self):
        log = '\n'.join(['Error: token=abc123secret', 'Authorization: Bearer xyz789'] +
                        ['x' * 120 + f' {i}' for i in range(60)])
        patcher, _ = network({'data': {'content': log}})
        with patcher:
            digest = req.log_digest(SN)
        self.assertLessEqual(len(digest), 1500)
        self.assertIn('x 59', digest)
        self.assertIn('Error: token=', digest)
        self.assertNotIn('abc123secret', digest)
        self.assertNotIn('xyz789', digest)

    def test_the_digest_falls_back_to_a_fixed_text(self):
        for log in (control.HttpStatusError('GET api.cnb.cool returned HTTP 500: ', 500), None,
                    {'data': {'content': []}}, {'data': None}):
            patcher, _ = network(log)
            with patcher:
                self.assertEqual('日志摘要获取失败', req.log_digest(SN))
        with patch.object(control, 'api', side_effect=AssertionError('no request without a build')):
            self.assertEqual('日志摘要获取失败', req.log_digest(''))

    def test_a_retry_dispatch_carries_the_digest_of_the_last_developer_build(self):
        comments = [self.marker('dev', 60, '', '2026-09-22T02:00:00Z')]
        rows = [self.attempt('error', '2026-09-22T02:00:00Z')]
        action = self.decide(comments, rows)
        self.assertEqual(('retry', SN), (action['phase'], action.get('sn')))
        sent = []
        patcher, _ = network({'data': {'content': ['step FAILED: export_test', 'run aborted']}})
        with patcher, patch.object(control, 'comment', side_effect=lambda *args: sent.append(args)):
            req.act(self.issue, action, '')
        self.assertIn('上一次开发构建的日志摘要', sent[0][1])
        self.assertIn('step FAILED: export_test', sent[0][1])

    def test_a_targeted_dispatch_after_diagnose_names_the_developer_build(self):
        comments = [self.marker('retry', 60, '', '2026-09-22T02:00:00Z'),
                    self.marker('diagnose', 60, '', '2026-09-22T02:20:00Z'),
                    self.report('改 core/log_history.go', '2026-09-22T02:25:00Z', role='审查助手')]
        rows = [self.attempt('error', '2026-09-22T02:00:00Z', sn='cnb-dev-7'),
                self.attempt('success', '2026-09-22T02:20:00Z', role='审查助手', sn='cnb-review-8')]
        action = self.decide(comments, rows)
        self.assertEqual(('targeted', 'cnb-dev-7'), (action['phase'], action.get('sn')))


if __name__ == '__main__':
    unittest.main()
