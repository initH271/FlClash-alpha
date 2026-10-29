import datetime
import io
import json
import unittest
from unittest.mock import patch

import pause

NOW = datetime.datetime.fromisoformat('2026-10-29T10:00:00+00:00')
HEAD = 'a' * 40
REF = 'automation/upstream-v0.9.3'
BODY = f'跟进上游。\n\nCNB Issue #217\n'


def at(minutes):
    return (NOW - datetime.timedelta(minutes=minutes)).isoformat().replace('+00:00', 'Z')


def candidate(number=12, ref=REF, head=HEAD, base='main', repo=None, body=BODY):
    return {'number': number, 'body': body,
            'base': {'ref': base},
            'head': {'ref': ref, 'sha': head,
                     'repo': {'full_name': repo or pause.POLICY['github']}}}


def run(title, status='in_progress', minutes=10):
    return {'display_title': title, 'status': status, 'created_at': at(minutes)}


def status_row(state='pending', minutes=10, context='FlClash/approved-build', created=None):
    return {'context': context, 'state': state, 'created_at': created or at(minutes)}


class LockCase(unittest.TestCase):
    """One lock read per test, against a world of pull requests, runs and comments."""

    def setUp(self):
        self.comment_bodies = []
        self.pulls = []
        self.runs = []
        self.statuses = []
        self.posted = []
        for name, effect in (('pages', self.reads), ('api', self.git_api), ('comment', self.write)):
            patcher = patch.object(pause, name, side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)
        reset = patch.object(pause, '_release', None)
        reset.start()
        self.addCleanup(reset.stop)

    def reads(self, url, *args, **kwargs):
        return list(self.pulls) if 'pulls' in url else list(self.comment_bodies)

    def git_api(self, url, method='GET', data=None):
        self.assertEqual('GET', method, url)
        if '/runs?' in url:
            return {'workflow_runs': list(self.runs)}
        if url.endswith('/status'):
            return {'statuses': list(self.statuses)}
        raise AssertionError('unexpected read ' + url)

    def write(self, number, body):
        self.posted.append((str(number), body))


class ReleaseLockTests(LockCase):
    def test_no_candidate_asks_for_nothing_else(self):
        with patch.object(pause, 'api') as api:
            self.assertIsNone(pause.release_lock(NOW))
        api.assert_not_called()

    def test_candidates_outside_the_upstream_branches_or_base_do_not_count(self):
        self.pulls = [candidate(ref='automation/req-9'), candidate(base='release'), candidate(repo='other/repo')]
        with patch.object(pause, 'api') as api:
            self.assertIsNone(pause.release_lock(NOW))
        api.assert_not_called()

    def test_an_unfinished_build_is_the_lock(self):
        self.pulls = [candidate()]
        for status in ('queued', 'in_progress'):
            self.runs = [run('Android ' + HEAD, status, 12), run('Android ' + HEAD, 'completed', 30)]
            with patch.object(pause, '_release', None):
                lock = pause.release_lock(NOW)
            self.assertEqual({'source': 'release', 'head': HEAD, 'ref': REF, 'pull': 12, 'since': at(12),
                              'minutes': 12, 'evidence': 'build.yaml 运行未结束', 'issue': '217'}, lock)

    def test_a_pending_approved_build_is_the_lock(self):
        self.pulls = [candidate()]
        self.statuses = [status_row(minutes=20)]
        lock = pause.release_lock(NOW)
        self.assertEqual(('release', HEAD, REF, 12, 20, 'approved-build 状态 pending', '217'),
                         (lock['source'], lock['head'], lock['ref'], lock['pull'], lock['minutes'],
                          lock['evidence'], lock['issue']))

    def test_finished_run_and_successful_status_leave_main_open(self):
        self.pulls = [candidate()]
        self.runs = [run('Android ' + HEAD, 'completed', 5)]
        self.statuses = [status_row('success', 5)]
        self.assertIsNone(pause.release_lock(NOW))

    def test_one_release_read_serves_the_whole_process(self):
        self.pulls = [candidate()]
        self.runs = [run('Android ' + HEAD, 'completed', 5)]
        self.statuses = [status_row(minutes=10)]
        asked = []
        pages, api = pause.pages, pause.api
        with patch.object(pause, 'pages', side_effect=lambda url, *a, **k: asked.append(url) or pages(url)), \
                patch.object(pause, 'api', side_effect=lambda url, *a, **k: asked.append(url) or api(url)):
            answers = [pause.paused('main', now=NOW) for _ in range(3)]
        self.assertEqual(1, len({json.dumps(answer, sort_keys=True) for answer in answers}))
        self.assertEqual(1, sum('/pulls?state=open' in url for url in asked))
        self.assertEqual(1, sum('/runs?' in url for url in asked))
        self.assertEqual(1, sum(url.endswith('/status') for url in asked))
        self.assertEqual(3, len(asked))

    def test_a_branch_scope_and_a_hold_outrank_the_release(self):
        owner = {'username': pause.POLICY['approver'], 'is_npc': False}
        hold = {'created_at': at(5), 'body': 'HOLD', 'author': owner}
        self.assertIsNone(pause.paused('branch', 'automation/req-9', [], now=NOW))
        self.assertEqual('hold', pause.paused('main', 'automation/req-9', [hold], now=NOW)['source'])


class ProductionCallTests(LockCase):
    """Call `paused` the way the controller calls it: no fixed clock, no comments."""

    def clock(self, minutes):
        return patch.object(pause, '_clock', return_value=NOW - datetime.timedelta(minutes=minutes))

    def pending(self, minutes, issue='217'):
        self.pulls = [candidate(body=f'跟进上游。\n\nCNB Issue #{issue}\n')]
        self.statuses = [status_row(minutes=minutes)]

    def test_an_expired_pending_status_does_not_lock_and_says_so_in_the_upgrade_issue(self):
        self.pending(181)
        with self.clock(0):
            self.assertIsNone(pause.paused('main', 'automation/security-sync-x'))
        self.assertEqual(['217'], [number for number, _ in self.posted])
        body = self.posted[0][1]
        self.assertTrue(body.startswith(pause.EXPIRED_MARKER.format(HEAD)))
        self.assertIn(HEAD[:12], body)
        self.assertIn('该候选不再算作发版锁', body)

    def test_a_pending_status_past_the_reminder_still_locks_and_reminds(self):
        self.pending(91)
        with self.clock(0):
            lock = pause.paused('main', 'automation/security-sync-x')
        self.assertEqual(91, lock['minutes'])
        self.assertEqual(1, len(self.posted))
        self.assertTrue(self.posted[0][1].startswith(pause.REMIND_MARKER.format(HEAD)))

    def test_the_clock_is_utc_aware(self):
        self.assertEqual(datetime.timezone.utc, pause._clock().tzinfo)


class CandidateTests(LockCase):
    def two(self, first, second):
        self.pulls = [candidate(number=1, head='a' * 40, body='跟进上游。\n\nCNB Issue #217\n'),
                      candidate(number=2, head='b' * 40, body='跟进上游。\n\nCNB Issue #218\n')]
        self.statuses = [status_row(minutes=first, created=at(first))] if first is not None else []

        def api(url, method='GET', data=None):
            if '/runs?' in url:
                return {'workflow_runs': []}
            return {'statuses': [status_row(minutes=first)]} if url.endswith('a' * 40 + '/status') \
                else {'statuses': [status_row(minutes=second)]}
        return patch.object(pause, 'api', side_effect=api)

    def test_a_candidate_expires_alone_while_the_other_still_locks(self):
        with self.two(181, 20):
            lock = pause.release_lock(NOW)
        self.assertEqual(('b' * 40, 'automation/upstream-v0.9.3', 2, 20),
                         (lock['head'], lock['ref'], lock['pull'], lock['minutes']))
        self.assertEqual(['217'], [number for number, _ in self.posted])
        self.assertIn('a' * 12, self.posted[0][1])
        self.assertIn('该候选不再算作发版锁', self.posted[0][1])

    def test_the_oldest_pending_candidate_is_the_lock(self):
        with self.two(30, 20):
            lock = pause.release_lock(NOW)
        self.assertEqual(30, lock['minutes'])
        self.assertEqual('a' * 40, lock['head'])

    def test_a_new_sha_on_the_same_branch_gets_its_own_reminder(self):
        self.pulls = [candidate(head='c' * 40)]
        self.statuses = [status_row(minutes=91)]
        self.comment_bodies = [{'body': pause.REMIND_MARKER.format('a' * 40)}]
        lock = pause.release_lock(NOW)
        self.assertEqual('c' * 40, lock['head'])
        self.assertEqual(1, len(self.posted))
        self.assertTrue(self.posted[0][1].startswith(pause.REMIND_MARKER.format('c' * 40)))


class ExpiryTests(LockCase):
    def pending(self, minutes, issue='217', notify=True, comments=()):
        body = f'跟进上游。\n\nCNB Issue #{issue}\n' if issue else '跟进上游。'
        self.pulls = [candidate(body=body)]
        self.statuses = [status_row(minutes=minutes)]
        self.comment_bodies = [{'body': body} for body in comments]
        return pause.release_lock(NOW, notify=notify)

    def test_a_pending_status_near_the_limit_still_locks(self):
        lock = self.pending(179)
        self.assertEqual(179, lock['minutes'])
        self.assertEqual(1, len(self.posted))
        self.assertTrue(self.posted[0][1].startswith(pause.REMIND_MARKER.format(HEAD)))
        self.assertIn(HEAD[:12], self.posted[0][1])
        self.assertNotIn('automation/u', self.posted[0][1])

    def test_the_limit_expires_the_lock_and_says_so_once(self):
        with patch.object(pause, '_release', None):
            self.assertTrue(self.pending(180))
        self.assertIsNone(self.pending(181))
        self.assertEqual('217', self.posted[-1][0])
        mark = pause.EXPIRED_MARKER.format(HEAD)
        self.assertIn(HEAD[:12], self.posted[-1][1])
        self.assertNotIn('automation/u', self.posted[-1][1])
        self.assertIn('@' + pause.POLICY['approver'], self.posted[-1][1])
        self.assertEqual(mark, self.posted[-1][1].splitlines()[0])
        posted = len(self.posted)
        with patch.object(pause, '_release', None):
            self.assertIsNone(self.pending(181, comments=[mark]))
        self.assertEqual(posted, len(self.posted))
        with patch.object(pause, '_release', None), patch('sys.stdout', new_callable=io.StringIO):
            self.assertIsNone(self.pending(181, notify=False))
        self.assertEqual(posted, len(self.posted))

    def test_reminders(self):
        self.assertTrue(self.pending(91))
        self.assertEqual(1, len(self.posted))
        self.assertTrue(self.posted[0][1].startswith(pause.REMIND_MARKER.format(HEAD)))
        self.assertIn('约 91 分钟', self.posted[0][1])
        self.assertIn('@' + pause.POLICY['approver'], self.posted[0][1])
        with patch.object(pause, '_release', None):
            self.posted = []
            self.assertTrue(self.pending(91, comments=[pause.REMIND_MARKER.format(HEAD)]))
        self.assertEqual(0, len(self.posted))
        with patch.object(pause, '_release', None):
            self.posted = []
            self.assertTrue(self.pending(89))
        self.assertEqual(0, len(self.posted))
        with patch.object(pause, '_release', None):
            self.posted = []
            self.assertTrue(self.pending(91, notify=False))
        self.assertEqual(0, len(self.posted))
        with patch.object(pause, '_release', None), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.posted = []
            self.assertTrue(self.pending(91, issue=''))
        self.assertEqual(0, len(self.posted))
        self.assertIn('91', out.getvalue())


class StatusTests(LockCase):
    def setUp(self):
        reset = patch.object(pause, '_release', None)
        reset.start()
        self.addCleanup(reset.stop)

    def test_status_outside_requirement_branches_reads_no_comments(self):
        asked = []

        def read(url, *args, **kwargs):
            asked.append(url)
            return [candidate()]

        def api(url, *args, **kwargs):
            asked.append(url)
            return {'workflow_runs': [run('Android ' + HEAD)]}

        with (patch.object(pause, 'pages', side_effect=read), patch.object(pause, 'api', side_effect=api),
              patch('sys.stdout', new_callable=io.StringIO)):
            pause.status('automation/security-sync-x')
        self.assertFalse([url for url in asked if '/comments' in url])

    def test_the_status_entrypoint_only_reads(self):
        owner = {'username': pause.POLICY['approver'], 'is_npc': False}
        hold = {'created_at': at(5), 'body': 'HOLD', 'author': owner}
        asked = []

        def pages(url, *args, **kwargs):
            asked.append(url)
            return [hold] if '/comments' in url else [candidate()]

        def api(url, method='GET', data=None):
            asked.append((method, url))
            if '/runs?' in url:
                return {'workflow_runs': [run('Android ' + HEAD)]}
            return {}

        with (patch.object(pause, 'pages', side_effect=pages), patch.object(pause, 'api', side_effect=api),
              patch.object(pause, 'comment') as post, patch('sys.stdout', new_callable=io.StringIO) as out):
            pause.status('automation/req-9')
        post.assert_not_called()
        self.assertEqual({'GET'}, {item[0] for item in asked if isinstance(item, tuple)})
        self.assertTrue(all(isinstance(item, str) or item[0] == 'GET' for item in asked))
        body = json.loads(out.getvalue().strip())
        self.assertEqual(('release', at(5)), (body['release']['source'], body['hold']))

    def test_status_without_a_branch_reports_the_release_only(self):
        with (patch.object(pause, 'pages', return_value=[]), patch.object(pause, 'api') as api,
              patch.object(pause, 'comment') as post, patch('sys.stdout', new_callable=io.StringIO) as out):
            pause.status()
        api.assert_not_called()
        post.assert_not_called()
        self.assertEqual({'release': None, 'hold': None}, json.loads(out.getvalue().strip()))
