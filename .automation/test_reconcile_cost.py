import collections
import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import review_evidence
import reviews
from test_review_snapshot import KEY, stamp

APPROVER = {'username': reviews.POLICY['approver'], 'is_npc': False}
PAGE = 100


class Cost:
    """CNB and GitHub as the HTTP layer shows them, counting each request a round makes."""

    def __init__(self, history):
        self.calls = collections.Counter()
        self.detail_reads = collections.Counter()
        self.issues, self.notes, self.notices, self.pulls = {}, {}, {}, {}
        self.statuses, self.next = {}, 1
        for index in range(history):
            # Old rounds of pulls that have since closed: signed, and closed, as CNB keeps them.
            old = {'platform': 'cnb', 'number': str(9000 + index), 'base': '0' * 40, 'head': f'{index:040x}'}
            self.add(reviews.review_title(old, 'old'), old, state='closed')

    def add(self, title, request, state='open', extra=''):
        number = str(self.next)
        self.next += 1
        self.issues[number] = {
            'number': number, 'state': state, 'title': title, 'author': APPROVER, 'created_at': stamp(10),
            'body': f'<!-- flclash-pr-review {json.dumps(reviews.sign(request))} -->{extra}'}
        self.notes[number] = []
        return self.issues[number]

    def add_pull(self, platform, number, base, head):
        self.pulls[platform, str(number)] = {
            'number': number, 'title': f'pull {number}', 'state': 'open', 'body': '', 'created_at': stamp(30),
            'base': {'sha': base, 'ref': 'main'}, 'head': {'sha': head, 'ref': f'feature/{number}'}}
        self.notices[platform, str(number)] = []
        return reviews.scope(platform, self.pulls[platform, str(number)])

    def notify(self, request, number):
        self.notices[request['platform'], request['number']].append(
            {'body': f'结对审核： https://cnb.cool/{reviews.POLICY["cnb"]}/-/issues/{number}'})

    def paged(self, rows):
        rows = list(rows)
        for start in range(0, max(len(rows), 1), PAGE):
            self.calls['issue_list_page' if self.listing else 'other_page'] += 1
            yield from rows[start:start + PAGE]

    def all_issues(self):
        self.listing = True
        for state in ('open', 'closed'):
            yield from self.paged([{key: value for key, value in issue.items() if key != 'body'}
                                   for issue in self.issues.values() if issue['state'] == state])
        self.listing = False

    listing = False

    def pages(self, url, page_key='page', size_key='page_size'):
        platform = 'github' if url.startswith(reviews.GH) else 'cnb'
        tail = url.removeprefix(reviews.GH if platform == 'github' else reviews.CNB)
        if tail == '/pulls?state=open':
            return self.paged(pull for (kind, _), pull in self.pulls.items() if kind == platform)
        if tail == '/issues?state=open':
            return self.paged(issue for issue in self.issues.values() if issue['state'] == 'open')
        parts = tail.strip('/').split('/')
        if parts[-1] == 'comments' and platform == 'cnb' and parts[0] == 'issues':
            return self.paged(self.notes[parts[1]])
        if parts[-1] == 'comments':
            return self.paged(self.notices[platform, parts[1]])
        raise AssertionError(f'unexpected list {url}')

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        platform = 'github' if url.startswith(reviews.GH) else 'cnb'
        tail = url.removeprefix(reviews.GH if platform == 'github' else reviews.CNB).strip('/')
        parts = tail.split('/')
        if method != 'GET':
            self.calls['write'] += 1
            return self.write(platform, parts, method, data)
        if parts[0] == 'issues':
            self.calls['issue_detail'] += 1
            self.detail_reads[parts[1]] += 1
            found = self.issues.get(parts[1])
            if found is None and not missing:
                raise AssertionError(f'unexpected 404 {url}')
            return dict(found) if found else None
        if parts[0] == 'pulls':
            self.calls['pull_detail'] += 1
            return dict(self.pulls[platform, parts[1]])
        if parts[0] == 'commits':
            self.calls['github_status'] += 1
            return {'statuses': list(self.statuses.get(parts[1], {}).values())}
        raise AssertionError(f'unexpected request {method} {url}')

    def write(self, platform, parts, method, data):
        if parts[0] == 'statuses':
            self.statuses.setdefault(parts[1], {})[data['context']] = {'target_url': data['target_url'], **data}
            return {}
        if parts[0] == 'issues' and len(parts) == 1:
            number = str(self.next)
            self.next += 1
            self.issues[number] = dict(data, number=number, state='open', author=APPROVER, created_at=stamp(0))
            self.notes[number] = []
            return dict(self.issues[number])
        if parts[0] == 'issues' and method == 'PATCH':
            self.issues[parts[1]].update(data)
            return {}
        if parts[-1] == 'comments' and parts[0] == 'issues' and platform == 'cnb':
            self.notes[parts[1]].append({'id': str(len(self.notes[parts[1]])), 'author': APPROVER,
                                         'created_at': stamp(0), 'body': data['body']})
            return {}
        if parts[-1] == 'comments':
            self.notices[platform, parts[1]].append({'body': data['body']})
            return {}
        raise AssertionError(f'unexpected write {method} {parts}')


class Commits:
    """A local repository whose heads each change `files` files, so a pull can be split into shards."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.run('init', '-q')
        self.base = self.commit(None, {'seed.txt': 'seed\n'})

    def run(self, *args, check=True, env=None, timeout=None):
        found = subprocess.run(['git', *args], cwd=self.root, env=env, text=True, capture_output=True, check=False)
        if check and found.returncode:
            raise RuntimeError(f'git {args[0]} failed: {found.stderr[-1500:]}')
        return found.stdout.strip() if check else found

    def commit(self, parent, files):
        if parent:
            self.run('checkout', '-q', '--detach', parent)
        for name, text in files.items():
            (self.root / name).write_text(text)
        self.run('add', *files)
        self.run('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                 'commit', '-q', '--no-verify', '-m', 'c')
        return self.run('rev-parse', 'HEAD')

    def head(self, label, files=1):
        return self.commit(self.base, {f'{label}-{i}.txt': f'{label}\n' for i in range(files)})


class ReconcileCostTests(unittest.TestCase):
    """How many requests one reconcile makes, which is what a slow round is made of on a 0.5s API."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Commits(cls.tmp.name)
        cls.heads = [cls.repo.head(f'pull{i}', files=2 if i == 0 else 1) for i in range(5)]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        for item in (patch.dict(os.environ, KEY), patch.object(reviews, 'SHARD_FILES', 1)):
            item.start()
            self.addCleanup(item.stop)

    def pulls(self, server):
        return [server.add_pull('cnb' if i == 4 else 'github', 121 + i, self.repo.base, head)
                for i, head in enumerate(self.heads)]

    def round(self, server):
        """One real reconcile over the real ensure_request, carry_over and close_finished_reviews."""
        fetches = []

        def git(*args, check=True, env=None, timeout=None):
            if args[0] == 'fetch':
                fetches.append(args)
                return '' if check else subprocess.CompletedProcess(args, 0, '', '')
            return self.repo.run(*args, check=check, env=env)
        printed = io.StringIO()
        started = time.monotonic()
        with (patch.object(reviews, 'api', side_effect=server.api),
              patch.object(reviews, 'pages', side_effect=server.pages),
              patch.object(reviews, 'all_issues', side_effect=server.all_issues),
              patch.object(reviews, 'git', git), patch.object(review_evidence, 'git', git),
              patch.object(reviews, 'requirement_brief', return_value=''),
              contextlib.redirect_stdout(printed)):
            reviews.reconcile()
        server.calls['fetch'] = len(fetches)
        server.printed, server.seconds = printed.getvalue(), time.monotonic() - started
        return server.calls

    def steady(self, history):
        """Five pulls that all have their open review already, the usual round."""
        server = Cost(history)
        for request in self.pulls(server):
            issue = server.add(reviews.review_title(request, f'pull {request["number"]}'), request)
            server.notify(request, issue['number'])
        return server

    def fresh(self, history):
        """Five pulls opened at once with no review yet, as #122-#125 were, one of them over the shard limit."""
        server = Cost(history)
        self.pulls(server)
        return server

    def test_a_new_head_costs_the_same_however_many_issues_exist(self):
        # Before: 2240 issue reads for five new pulls over 370 old issues, 4460 over 740, about 19 minutes at 0.5s.
        calls = [self.round(self.fresh(history)) for history in (370, 740)]
        self.assertEqual(calls[0]['issue_detail'], calls[1]['issue_detail'])
        self.assertLessEqual(calls[0]['issue_detail'], 10)
        self.assertLessEqual(calls[0]['issue_list_page'], 5)

    def test_a_usual_round_reads_each_issue_once(self):
        server = self.steady(370)
        calls = self.round(server)
        self.assertLessEqual(calls['issue_detail'], 5)
        self.assertEqual({1}, set(server.detail_reads.values()))
        self.assertLessEqual(calls['issue_list_page'], 5)

    def test_a_whole_round_fits_a_minute_of_half_second_requests(self):
        for scenario in (self.steady, self.fresh):
            calls = self.round(scenario(370))
            self.assertLess(sum(calls.values()) - calls['fetch'], 120, scenario.__name__)

    def test_earlier_rounds_of_a_pull_are_each_read_once_in_a_round(self):
        server = self.fresh(370)
        request = reviews.scope('github', server.pulls['github', '121'])
        for index in range(20):
            old = dict(request, head=f'{index:040x}')
            issue = server.add(reviews.review_title(old, 'pull 121'), old, state='closed')
            server.notify(request, issue['number'])
        calls = self.round(server)
        self.assertEqual({1}, set(server.detail_reads.values()))
        self.assertLessEqual(calls['issue_detail'], 30)

    def opened(self, server):
        return [issue for issue in server.issues.values() if issue['state'] == 'open']

    def blocked_review(self, server, request, title, state='closed'):
        issue = server.add(title, request, state=state)
        server.notify(request, issue['number'])
        return issue

    def test_a_closed_review_of_the_same_head_still_fails_the_gate_behind_all_that_history(self):
        server = self.fresh(370)
        request = reviews.scope('github', server.pulls['github', '121'])
        issue = server.add(reviews.review_title(request, 'pull 121'), request, state='closed')
        before = len(server.issues)
        self.round(server)
        self.assertEqual('failure', server.statuses[request['head']][reviews.CONTEXT]['state'])
        self.assertIn(f'/issues/{issue["number"]}', server.statuses[request['head']][reviews.CONTEXT]['target_url'])
        self.assertEqual(before + 4, len(server.issues), 'only the four other pulls open a review')

    def test_a_closed_review_renamed_by_hand_still_fails_the_gate(self):
        server = self.fresh(370)
        request = reviews.scope('github', server.pulls['github', '121'])
        server.add('人工修改过的标题', request, state='closed')
        self.round(server)
        self.assertEqual('failure', server.statuses[request['head']][reviews.CONTEXT]['state'])

    def test_a_closed_review_renamed_to_another_pull_is_still_found_through_its_notice(self):
        server = self.fresh(370)
        request = reviews.scope('github', server.pulls['github', '121'])
        self.blocked_review(server, request, '[PR审核] CNB #9000：看起来是别的 PR')
        self.round(server)
        self.assertEqual('failure', server.statuses[request['head']][reviews.CONTEXT]['state'])

    def test_a_title_alone_proves_nothing(self):
        server = self.fresh(370)
        request = reviews.scope('github', server.pulls['github', '121'])
        forged = server.add(reviews.review_title(request, 'pull 121'), request)
        forged['body'] = forged['body'].replace('"signature": "', '"signature": "00')
        unsigned = server.add(reviews.review_title(request, 'pull 121'), request)
        unsigned['body'] = 'no marker'
        self.round(server)
        target = server.statuses[request['head']][reviews.CONTEXT]['target_url']
        self.assertFalse(target.endswith((f'/{forged["number"]}', f'/{unsigned["number"]}')))
        self.assertEqual('pending', server.statuses[request['head']][reviews.CONTEXT]['state'])

    def test_each_pull_logs_its_number_and_time_and_nothing_else(self):
        server = self.steady(5)
        self.round(server)
        for number in range(121, 125):
            self.assertRegex(server.printed, rf'(?m)^github PR #{number}: \d+\.\d+s$')
        self.assertRegex(server.printed, r'(?m)^cnb PR #125: \d+\.\d+s$')
        self.assertNotIn('flclash-pr-review', server.printed)

    def test_a_raising_pull_logs_its_line_and_the_next_pull_still_runs(self):
        server = self.steady(5)
        printed = io.StringIO()
        with (patch.object(reviews, 'close_finished_reviews'),
              patch.object(reviews, 'pages', side_effect=server.pages),
              patch.object(reviews, '_reconcile_pull', side_effect=RuntimeError('boom')),
              contextlib.redirect_stdout(printed), self.assertRaises(reviews.RoundIncomplete)):
            reviews.reconcile()
        self.assertRegex(printed.getvalue(), r'(?m)^github PR #121: \d+\.\d+s$')
        self.assertRegex(printed.getvalue(), r'(?m)^github PR #122: \d+\.\d+s$')


class RoundCacheTests(unittest.TestCase):
    """What one round may remember, and what a write takes away from it."""

    def setUp(self):
        self.server = Cost(0)
        for item in (patch.dict(os.environ, KEY),
                     patch.object(reviews, 'api', side_effect=self.server.api),
                     patch.object(reviews, 'pages', side_effect=self.server.pages),
                     patch.object(reviews, 'all_issues', side_effect=self.server.all_issues)):
            item.start()
            self.addCleanup(item.stop)
        self.request = {'platform': 'github', 'number': '7', 'base': 'a' * 40, 'head': 'b' * 40}
        self.server.add_pull('github', 7, 'a' * 40, 'b' * 40)
        self.number = self.server.add(reviews.review_title(self.request, 't'), self.request)['number']
        self.url = f'{reviews.CNB}/issues/{self.number}'

    def test_outside_a_round_every_read_is_fresh(self):
        reviews.find_request(self.request)
        reviews.find_request(self.request)
        self.assertEqual(2, self.server.calls['issue_detail'])
        self.assertIsNone(reviews._round)

    def test_a_round_ends_with_the_block_that_opened_it_even_on_an_error(self):
        with self.assertRaises(RuntimeError), reviews._one_round():
            raise RuntimeError('boom')
        self.assertIsNone(reviews._round)

    def test_a_comment_makes_the_issue_read_again(self):
        with reviews._one_round():
            reviews._issue(self.number)
            reviews._issue(self.number)
            self.assertEqual(1, self.server.calls['issue_detail'])
            reviews._write(f'{self.url}/comments', 'POST', {'body': 'x'})
            reviews._issue(self.number)
            self.assertEqual(2, self.server.calls['issue_detail'])

    def test_a_patch_shows_in_the_next_read_of_the_issue_and_of_the_list(self):
        with reviews._one_round():
            self.assertEqual('open', reviews._issue(self.number)['state'])
            self.assertEqual('open', list(reviews._titled(self.request))[0]['state'])
            reviews._write(self.url, 'PATCH', {'state': 'closed'})
            self.assertEqual('closed', reviews._issue(self.number)['state'])
            self.assertEqual('closed', list(reviews._titled(self.request))[0]['state'])

    def test_a_new_issue_is_found_later_in_the_round_without_listing_again(self):
        other = dict(self.request, head='c' * 40)
        with reviews._one_round():
            self.assertIsNone(reviews.find_request(other))
            pages = self.server.calls['issue_list_page']
            created = reviews._write(f'{reviews.CNB}/issues', 'POST', {
                'title': reviews.review_title(other, 't'),
                'body': f'<!-- flclash-pr-review {json.dumps(reviews.sign(other))} -->'})
            self.assertEqual(created['number'], reviews.find_request(other)['number'])
            self.assertIsNot(created, reviews._round['rows'][0])
            self.assertEqual(pages, self.server.calls['issue_list_page'])

    def test_a_missing_issue_is_not_remembered(self):
        with reviews._one_round():
            self.assertIsNone(reviews._issue(999, missing=True))
            self.server.issues['999'] = dict(self.server.issues[self.number], number='999')
            self.assertEqual('999', reviews._issue(999, missing=True)['number'])

    def test_every_write_in_the_module_goes_through_the_one_that_invalidates(self):
        source = pathlib.Path(reviews.__file__).read_text()
        self.assertEqual([], re.findall(r"\bapi\([^()]*(?:\([^()]*\)[^()]*)*'(?:POST|PATCH)'", source))


class RenamedPullTests(unittest.TestCase):
    """A pull renamed after its review opened, whose review then closed with a block, behind a long history."""

    def setUp(self):
        key = patch.dict(os.environ, KEY)
        key.start()
        self.addCleanup(key.stop)
        self.server = Cost(370)
        for item in (patch.object(reviews, 'api', side_effect=self.server.api),
                     patch.object(reviews, 'pages', side_effect=self.server.pages),
                     patch.object(reviews, 'all_issues', side_effect=self.server.all_issues)):
            item.start()
            self.addCleanup(item.stop)
        self.request = {'platform': 'github', 'number': '7', 'base': 'a' * 40, 'head': 'b' * 40}
        self.server.add_pull('github', 7, 'a' * 40, 'b' * 40)
        # No notice on the pull: the list row alone has to lead to this issue.
        self.issue = self.server.add(reviews.review_title(self.request, '旧标题'), self.request)
        self.issue['title'] = reviews.review_title(self.request, '新标题')
        self.issue['state'] = 'closed'
        role = reviews.ROLES[0]
        report = {'request': reviews.identity(self.request), 'verdict': 'block', 'blockers': 1}
        self.server.notes[self.issue['number']].append({
            'id': '1', 'created_at': stamp(0), 'body': 'FLCLASH_REVIEW ' + json.dumps(report),
            'author': {'username': f'{reviews.POLICY["cnb"]}({role})', 'is_npc': True}})

    def test_find_request_reaches_it_reading_only_that_issue(self):
        self.assertEqual(self.issue['number'], reviews.find_request(self.request)['number'])
        self.assertEqual(1, self.server.calls['issue_detail'])

    def test_its_block_still_fails_the_gate(self):
        self.assertEqual('failure', reviews.state(self.request))
        self.assertEqual(1, self.server.calls['issue_detail'])
        notes = self.server.notes[self.issue['number']]
        self.assertEqual('block', reviews.role_reports(self.request, self.issue, notes)[reviews.ROLES[0]])


class FetchTests(unittest.TestCase):
    """A fetch has a wall clock, and a round does not repeat one that already failed."""

    request = {'platform': 'cnb', 'number': '1', 'base': 'a' * 40, 'head': 'b' * 40}

    def run_rounds(self, codes, requests):
        fetched = []

        def git(*args, check=True, env=None, timeout=None):
            if args[0] == 'fetch':
                fetched.append((args, timeout))
                return subprocess.CompletedProcess(args, codes[len(fetched) - 1], '', '')
            return subprocess.CompletedProcess(args, 1, '', '')
        with patch.object(reviews, 'git', git), reviews._one_round():
            answers = [reviews._fetch_rounds(request, []) for request in requests]
        return answers, fetched

    def test_after_a_timeout_another_pull_does_not_wait_on_that_remote(self):
        # Its missing commits differ, so only a remote-wide memory can spare it. The second answer would be a success.
        other = dict(self.request, head='c' * 40)
        answers, fetched = self.run_rounds([reviews.GIT_TIMED_OUT, 0], [self.request, other])
        self.assertEqual([False, False], answers)
        self.assertEqual(1, len(fetched))
        self.assertNotIn('c' * 40, fetched[0][0])

    def test_the_fetch_it_does_make_carries_the_timeout(self):
        answers, fetched = self.run_rounds([0], [self.request])
        self.assertEqual([True], answers)
        self.assertEqual(reviews.FETCH_TIMEOUT, fetched[0][1])

    def test_a_plain_failure_only_rules_out_the_same_commits(self):
        other = dict(self.request, head='c' * 40)
        answers, fetched = self.run_rounds([1, 0], [self.request, self.request, other])
        self.assertEqual([False, False, True], answers)
        self.assertEqual(2, len(fetched))

    def test_control_git_turns_a_timeout_into_a_failure_it_can_report(self):
        import control
        hung = subprocess.TimeoutExpired('git', 1)
        with patch.object(control.subprocess, 'run', side_effect=hung):
            self.assertEqual(control.GIT_TIMED_OUT, control.git('fetch', 'x', check=False, timeout=1).returncode)
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                control.git('fetch', 'x', timeout=1)


if __name__ == '__main__':
    unittest.main()
