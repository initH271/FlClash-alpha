import contextlib
import io
import json
import unittest
from unittest.mock import patch

import control
import status

NOW = 1_800_000_000.0
HOUR = 3600
CNB_URL = 'https://cnb.cool/507space/FlClash-alpha/-'


def iso(seconds_ago):
    import datetime
    moment = datetime.datetime.fromtimestamp(NOW - seconds_ago, datetime.timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def row(pull, requirement, phase='dev', age=3 * HOUR, state='open', hold=None, title='需求实现'):
    return {'pull': pull, 'requirement': requirement, 'title': title, 'age': age,
            'state': state, 'phase': phase, 'hold': hold}


def snapshot(pulls=(), upgrades=(), builds=(), release=None):
    return {'pulls': list(pulls), 'upgrades': list(upgrades), 'builds': list(builds),
            'release': release or {'tag': 'v0.9.2-alpha.17', 'ahead': 0}}


class RenderTests(unittest.TestCase):
    def test_empty_state_lists_every_section_as_none(self):
        self.assertEqual(
            '## 需求 PR\n- 无\n\n## 待 owner OK 的升级\n- 无\n\n## 发版\n'
            '- GitHub main 与最新 release v0.9.2-alpha.17 一致\n\n## 正在运行的 NPC 构建\n- 无\n',
            status.render(snapshot()))

    def test_halted_held_and_orphaned_requirements_stand_out(self):
        body = status.render(snapshot(pulls=[
            row('12', '9'), row('13', '10', 'stuck', age=50 * HOUR), row('14', '11', 'quota'),
            row('15', '20', hold=3 * HOUR), row('16', '21', hold=HOUR), row('17', '22', state='closed')]))
        self.assertIn(f'- PR [#12]({CNB_URL}/pulls/12) 需求实现：开了 3 小时，需求 [#9]({CNB_URL}/issues/9) dev\n', body)
        self.assertIn(f'开了 2 天，需求 [#10]({CNB_URL}/issues/10) **【stuck】**\n', body)
        self.assertIn('**【quota】**', body)
        self.assertIn(f'[#20]({CNB_URL}/issues/20) **【HOLD】** dev\n', body)
        self.assertIn(f'[#22]({CNB_URL}/issues/22) **【需求已关闭，孤儿 PR】**\n', body)
        held = body.split('### HOLD 超过 2 小时\n')[1].split('\n\n')[0]
        self.assertEqual(f'- 需求 [#20]({CNB_URL}/issues/20)（PR [#15]({CNB_URL}/pulls/15)）：HOLD 已 3 小时', held)

    def test_a_short_hold_gets_no_separate_section(self):
        self.assertNotIn('### HOLD', status.render(snapshot(pulls=[row('16', '21', hold=HOUR)])))

    def test_upgrades_lead_and_running_builds(self):
        body = status.render(snapshot(
            upgrades=[{'issue': '159', 'tag': 'v0.9.3', 'waited': 4 * 86400 + HOUR}],
            builds=[{'issue': '9', 'role': '开发助手', 'sn': 'cnb-1', 'elapsed': 45 * 60}],
            release={'tag': 'v0.9.2-alpha.17', 'ahead': 5}))
        self.assertIn(f'## 待 owner OK 的升级\n- [#159]({CNB_URL}/issues/159) v0.9.3：等了 4 天\n', body)
        self.assertIn('- **GitHub main 领先最新 release v0.9.2-alpha.17 5 个提交**\n', body)
        self.assertIn(f'- 需求 [#9]({CNB_URL}/issues/9) 开发助手 构建 `cnb-1`：已运行 40 分钟\n', body)

    def test_an_unreadable_release_says_why(self):
        body = status.render(snapshot(release={'tag': 'v1', 'ahead': None, 'note': 'GitHub 读取失败'}))
        self.assertIn('- 最新 release v1：GitHub 读取失败\n', body)

    def test_spans_are_coarse_so_the_body_rarely_changes(self):
        self.assertEqual(['不到 10 分钟', '50 分钟', '2 小时', '47 小时', '2 天'],
                         [status.span(s) for s in (300, 59 * 60, 2 * HOUR, 47 * HOUR + 59 * 60, 48 * HOUR)])


class PublishTests(unittest.TestCase):
    def run_publish(self, issues, details):
        calls = []

        def api(url, method='GET', data=None, missing=False, timeout=60):
            calls.append((method, url, data))
            if method == 'POST':
                return {'number': '300'}
            if method == 'PATCH':
                return {}
            return details.get(url.rsplit('/', 1)[1])
        with patch.object(status, 'api', side_effect=api), contextlib.redirect_stdout(io.StringIO()):
            status.publish('## 需求 PR\n- 无\n', issues)
        return [call for call in calls if call[0] != 'GET']

    def test_a_found_issue_is_patched_in_place(self):
        writes = self.run_publish([{'number': '5', 'title': '别的'}, {'number': '7', 'title': status.TITLE}],
                                  {'7': {'body': status.MARKER + '\n\n旧内容'}})
        self.assertEqual([('PATCH', f'{status.CNB}/issues/7',
                           {'body': status.MARKER + '\n\n## 需求 PR\n- 无\n'})], writes)

    def test_an_unchanged_body_is_not_written(self):
        body = (status.MARKER + '\n\n## 需求 PR\n- 无\n').replace('\n', '\r\n')
        self.assertEqual([], self.run_publish([{'number': '7', 'title': status.TITLE}], {'7': {'body': body}}))

    def test_a_missing_issue_is_created_once(self):
        writes = self.run_publish([{'number': '8', 'title': status.TITLE}], {'8': {'body': '同名但没有标记'}})
        self.assertEqual(1, len(writes))
        method, url, data = writes[0]
        self.assertEqual(('POST', f'{status.CNB}/issues', status.TITLE), (method, url, data['title']))
        self.assertTrue(data['body'].startswith(status.MARKER))
        self.assertNotIn('@', data['body'])


def signed(phase, created, ident):
    return {'id': ident, 'created_at': created, 'author': {'username': 'Aharon', 'is_npc': False},
            'body': '<!-- flclash-requirement ' + json.dumps({'payload': {'phase': phase}, 'signature': 'x'}) + ' -->'}


class CollectTests(unittest.TestCase):
    def test_collect_reads_requirements_upgrades_builds_and_release_lead(self):
        owner = {'username': 'Aharon', 'is_npc': False}
        running = {'npc': [{'context': {'npc.slug': status.POLICY['cnb'], 'npc.name': '开发助手', 'sn': 'cnb-7'},
                            'statuses': [{'state': 'pending'}]}]}
        comments = {
            '9': [dict(signed('stuck', iso(5 * HOUR), '1'), statuses=running),
                  {'id': '2', 'created_at': iso(3 * HOUR), 'author': owner, 'body': 'HOLD'}],
            '10': [signed('dev', iso(HOUR), '3')],
            '159': [], '160': [{'id': '4', 'author': owner, 'body': 'OK', 'created_at': iso(HOUR)}]}
        issues = [{'number': 9, 'title': '[需求] 加功能', 'author': owner},
                  {'number': 159, 'title': '[上游升级] FlClash v0.9.3', 'created_at': iso(4 * 86400)},
                  {'number': 160, 'title': '[上游升级] FlClash v0.9.4', 'created_at': iso(86400)},
                  {'number': 161, 'title': '[上游升级] FlClash v0.9.1', 'created_at': iso(86400)}]
        pulls = [{'number': 12, 'title': '实现 @someone', 'created_at': iso(26 * HOUR),
                  'head': {'ref': 'refs/heads/automation/req-9'}},
                 {'number': 13, 'title': 'x', 'created_at': iso(HOUR), 'head': {'ref': 'automation/req-10'}},
                 {'number': 14, 'title': 'y', 'created_at': iso(HOUR), 'head': {'ref': 'sync/x'}}]

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if '/releases/tags/' in url:
                return {'tag_name': 'v0.9.2-alpha.17'}
            if '/compare/v0.9.2-alpha.17...main' in url:
                return {'ahead_by': 4}
            if url.endswith('/issues/9'):
                return {'number': 9, 'state': 'open'}
            if url.endswith('/issues/10'):
                return {'number': 10, 'state': 'closed'}
            raise AssertionError(f'unexpected {method} {url}')

        def pages(url, page_key='page', size_key='page_size'):
            if url.endswith('/pulls?state=open'):
                return iter(pulls)
            return iter(comments[url.split('/issues/')[1].split('/')[0]])
        with (patch.object(status, 'api', side_effect=api), patch.object(status, 'pages', side_effect=pages),
              patch.object(status, 'release_identity', return_value={'tag': 'v0.9.2-alpha.17'})):
            found = status.collect(issues, NOW)
        self.assertEqual([row('12', '9', 'stuck', 26 * HOUR, hold=3 * HOUR, title='实现 ＠someone'),
                          row('13', '10', 'dev', HOUR, 'closed', title='x')], found['pulls'])
        self.assertEqual([{'issue': '159', 'tag': 'v0.9.3', 'waited': 4 * 86400}], found['upgrades'])
        self.assertEqual([{'issue': '9', 'role': '开发助手', 'sn': 'cnb-7', 'elapsed': 5 * HOUR}], found['builds'])
        self.assertEqual({'tag': 'v0.9.2-alpha.17', 'ahead': 4}, found['release'])

    def test_a_github_failure_leaves_the_lead_unknown(self):
        def api(url, method='GET', data=None, missing=False, timeout=60):
            raise control.HttpStatusError('GET api.github.com returned HTTP 403: ', 403)
        with patch.object(status, 'api', side_effect=api):
            lead = status.release_lead()
        self.assertEqual((None, 'GitHub 读取失败'), (lead['ahead'], lead['note']))


if __name__ == '__main__':
    unittest.main()


# A comment as CNB returns it for a running NPC build (trimmed from a real #393 comment; the build is
# still going, so only its state differs from the real "success" one). Every value is a JSON string.
REAL_RUNNING_COMMENT = """{"id": "2116203539910107136", "created_at": "2026-10-30T16:20:15Z",
 "updated_at": "2026-10-30T16:20:15Z", "author": {"username": "507space/FlClash-alpha(审查助手)", "is_npc": true},
 "reactions": [], "body": "@Aharon 复核中",
 "statuses": {"npc": [{"key": {"name": "审查助手", "slug": "507space/FlClash-alpha"},
  "context": {"npc.name": "审查助手", "npc.slug": "507space/FlClash-alpha", "npc.work_mode": "false",
              "pipeline_id": "cnb-h8t-1k66poe3u-001", "sha": "412c4b197d92a59695776c177f70af1bed71a879",
              "sn": "cnb-h8t-1k66poe3u"},
  "statuses": [{"state": "pending", "context": "cnb/issue.comment@npc/pipeline-1(Project NPC review)",
                "description": "pending", "target_url": "https://cnb.cool/507space/FlClash-alpha/-/build/logs/cnb-h8t-1k66poe3u"}],
  "annotations": {"milli_credit": "0", "total_tokens": "0"}}]}}"""


class RealShapeTests(unittest.TestCase):
    def test_a_running_npc_build_in_the_real_comment_shape_reaches_the_rendered_status(self):
        comment = json.loads(REAL_RUNNING_COMMENT)
        now = 1_793_377_215.0 + 40 * 60  # 2026-10-30T16:20:15Z plus forty minutes
        issues = [{'number': 393, 'title': '[需求] 真实形状', 'author': {'username': 'Aharon', 'is_npc': False}}]

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if url.endswith('/issues/393'):
                return {'number': 393, 'state': 'open', 'statuses': None}
            raise AssertionError(f'unexpected {method} {url}')

        def pages(url, page_key='page', size_key='page_size'):
            return iter([comment] if url.endswith('/issues/393/comments') else [])
        with (patch.object(status, 'api', side_effect=api), patch.object(status, 'pages', side_effect=pages),
              patch.object(status, 'release_lead', return_value={'tag': 'v0.9.2-alpha.19', 'ahead': 0})):
            found = status.collect(issues, now)
        self.assertEqual([{'issue': '393', 'role': '审查助手', 'sn': 'cnb-h8t-1k66poe3u', 'elapsed': 40 * 60}],
                         found['builds'])
        self.assertIn('审查助手 构建 `cnb-h8t-1k66poe3u`：已运行 ', status.render(found))


class WatchdogStatusTests(unittest.TestCase):
    def test_a_status_failure_is_logged_with_its_message_and_does_not_stop_the_watchdog(self):
        import wake
        out = io.StringIO()
        with (patch.object(wake, 'watchdog') as watchdog,
              patch.object(status, 'refresh', side_effect=control.HttpStatusError(
                  'POST api.cnb.cool returned HTTP 500: boom', 500)),
              contextlib.redirect_stdout(out)):
            wake.watchdog_with_status()
        watchdog.assert_called_once()
        self.assertIn('Status issue skipped: HttpStatusError: POST api.cnb.cool returned HTTP 500: boom',
                      out.getvalue())
