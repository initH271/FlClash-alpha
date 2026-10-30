import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import reviews
from test_review_snapshot import KEY, Repo, stamp

CNB_NAMES = ('Dependency vulnerability gate', 'Automation unit tests', 'Go dependency regression tests',
             'Flutter and Android requirement tests', 'Rust dependency regression tests')


def checks(state, minutes):
    return {'statuses': [{'context': f'cnb/pipeline-{i}({name})', 'state': state, 'created_at': stamp(minutes)}
                         for i, name in enumerate(CNB_NAMES)]}


def run(status, conclusion=None):
    """A check run as GitHub's `/commits/{ref}/check-runs` lists it."""
    return {'name': 'build', 'status': status, 'conclusion': conclusion}


class Server:
    """CNB and GitHub as the HTTP layer shows them, and nothing more."""

    def __init__(self, platform, pull):
        self.platform, self.pull, self.statuses = platform, pull, checks('success', 90)
        self.runs, self.extra = [run('completed', 'success')], []
        self.issues, self.comments, self.pulls, self.github, self.full = {}, {}, {}, {}, []

    def add_issue(self, body):
        number = str(77 + len(self.issues))
        self.issues[number] = {'number': number, 'state': 'open', 'created_at': stamp(0), 'title': 't',
                               'author': {'username': reviews.POLICY['approver'], 'is_npc': False}, 'body': body}
        self.comments[number] = []
        return self.issues[number]

    def note(self, number, body, author=None, created=None):
        rows = self.comments[number]
        rows.append({'id': str(len(rows) + 1), 'body': body, 'created_at': created or stamp(0),
                     'author': author or {'username': reviews.POLICY['approver'], 'is_npc': False}})

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        number = str(self.pull['number'])
        if url.endswith('/commit-statuses'):
            return self.statuses
        if url.endswith(f'/pulls/{number}') and method == 'GET':
            return dict(self.pull)
        if '/check-runs?' in url:
            return {'total_count': len(self.runs), 'check_runs': self.runs}
        if url.endswith('/status'):
            gate = list(self.github.get(url.split('/')[-2], {}).values())
            return {'state': 'pending', 'statuses': gate + self.extra}
        if '/statuses/' in url:
            if url.startswith(reviews.GH):
                self.github.setdefault(url.split('/')[-1], {})[data['context']] = data
            return {}
        if url.endswith('/issues') and method == 'POST':
            return {'number': self.add_issue(data['body'])['number'], 'state': 'open'}
        if url.endswith('/comments') and method == 'POST':
            if '/issues/' in url and url.startswith(reviews.CNB):
                self.note(url.split('/')[-2], data['body'])
            else:
                self.pulls.setdefault(number, []).append({'body': data['body']})
            return {}
        if '/issues/' in url and method == 'GET':
            return self.issues.get(url.split('/')[-1])
        raise AssertionError(f'unexpected request {method} {url}')

    def pages(self, url, page_key='page', size_key='page_size'):
        if '/pulls?state=open' in url:
            return iter([self.pull] if url.startswith(reviews.endpoint(self.platform)) else [])
        if '/issues/' in url and url.startswith(reviews.CNB) and url.endswith('/comments'):
            return iter(self.comments.get(url.split('/')[-2], []))
        if url.endswith('/comments'):
            return iter(self.pulls.get(url.split('/')[-2], []))
        return iter([])

    def ensure_request(self, request, title, brief=''):
        for issue in self.issues.values():
            if reviews.request_from(issue) == request:
                return issue
        self.full.append(request)
        issue = self.add_issue('<!-- flclash-pr-review ' + json.dumps(reviews.sign(request)) + ' -->')
        self.pulls.setdefault(request['number'], []).append(
            {'body': f'结对审核： https://cnb.cool/{reviews.POLICY["cnb"]}/-/issues/{issue["number"]}'})
        return issue


class ReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Repo(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        for item in (patch.dict(os.environ, KEY), patch.object(reviews, 'git', self.repo.git)):
            item.start()
            self.addCleanup(item.stop)

    def run_pass(self, server):
        printed = io.StringIO()
        with (patch.object(reviews, 'api', side_effect=server.api),
              patch.object(reviews, 'pages', side_effect=server.pages),
              patch.object(reviews, 'ensure_request', side_effect=server.ensure_request),
              patch.object(reviews, 'close_finished_reviews'), patch.object(reviews, 'reconsider'),
              patch.object(reviews, 'requirement_brief', return_value=''),
              contextlib.redirect_stdout(printed)):
            reviews.reconcile()
        return printed.getvalue()

    def move(self, server, base, head, ci=('success', 5)):
        """Close the open review Issues as superseded, move the pull, rerun CI and reconcile."""
        for issue in server.issues.values():
            issue['state'] = 'closed'
        server.pull.update(base={'sha': base}, head={'sha': head, 'ref': server.pull['head']['ref']})
        server.statuses = checks(*ci)
        return self.run_pass(server)

    def review(self, server, base, head, verdicts):
        """A full review round of base/head whose reporters return these verdicts, seen by two passes."""
        self.move(server, base, head, ('success', 90))
        request = reviews.scope(server.platform, server.pull)
        issue = next(i for i in server.issues.values() if reviews.request_from(i) == request)
        issue['created_at'] = stamp(60)
        for role, verdict in zip(reviews.ROLES, verdicts):
            report = {'request': reviews.identity(request), 'verdict': verdict, 'blockers': int(verdict != 'pass')}
            server.note(issue['number'], 'FLCLASH_REVIEW ' + json.dumps(report), created=stamp(50),
                        author={'username': f'{reviews.POLICY["cnb"]}({role})', 'is_npc': True})
        self.run_pass(server)
        return issue

    def scenario(self, base, head, verdicts=('pass', 'pass'), platform='github', ref='sync/x',
                 ci=('success', 5), source='12'):
        """Fully review the patch on b1, then move the pull to base/head and reconcile again."""
        pull = {'number': source, 'title': '改动', 'state': 'open', 'base': {'sha': self.repo.b1},
                'head': {'sha': self.repo.h1, 'ref': ref}, 'created_at': stamp(200)}
        server = Server(platform, pull)
        issue = self.review(server, self.repo.b1, self.repo.h1, verdicts)
        if source != '12':
            server.pulls['12'] = server.pulls.pop(source)
            pull['number'] = '12'
        server.full.clear()
        return server, issue, self.move(server, base, head, ci)

    def reused(self, server):
        return [i for i in server.issues.values() if '<!-- flclash-review-reuse ' in i['body']]

    def assert_full(self, server, label=None):
        self.assertEqual((1, []), (len(server.full), self.reused(server)), label)

    def test_forward_base_and_same_patch_reuse_the_double_pass(self):
        server, source, printed = self.scenario(self.repo.b2, self.repo.h2)
        self.assertEqual([], server.full)
        (issue,) = self.reused(server)
        digest = reviews.patch_id(self.repo.b1, self.repo.h1)
        payload = json.loads(reviews.REUSE.search(issue['body'])[1])['payload']
        self.assertEqual((digest, digest, source['number'], self.repo.h1),
                         (payload['patch_id'], payload['source_patch_id'], payload['source_issue'],
                          payload['source_head']))
        self.assertIn(f'/-/issues/{source["number"]}', issue['body'])
        self.assertNotIn('@', issue['body'])
        status = server.github[self.repo.h2][reviews.CONTEXT]
        self.assertEqual('success', status['state'])
        self.assertTrue(status['target_url'].endswith(f'/-/issues/{issue["number"]}'))
        self.assertIn('reused review', printed)

    def test_github_reuse_needs_every_other_check_to_succeed(self):
        gate = {'context': reviews.CONTEXT, 'state': 'success'}
        cases = {'pending run': ([run('in_progress')], []), 'failed run': ([run('completed', 'failure')], []),
                 'failed status': ([run('completed', 'success')], [{'context': 'ci', 'state': 'failure'}]),
                 'only the gate': ([run('completed', 'skipped'), run('completed', 'neutral')], [gate])}
        for label, (runs, extra) in cases.items():
            pull = {'number': '12', 'title': '改动', 'state': 'open', 'base': {'sha': self.repo.b1},
                    'head': {'sha': self.repo.h1, 'ref': 'x'}}
            server = Server('github', pull)
            self.review(server, self.repo.b1, self.repo.h1, ('pass', 'pass'))
            server.full.clear()
            server.runs, server.extra = runs, extra
            self.move(server, self.repo.b2, self.repo.h2)
            self.assert_full(server, label)
            self.assertNotEqual('success', server.github[self.repo.h2][reviews.CONTEXT]['state'], label)

    def test_cnb_reuse_waits_for_fresh_ci_and_only_a_verified_marker_passes(self):
        server, _, printed = self.scenario(self.repo.b2, self.repo.h2, platform='cnb',
                                           ref='refs/heads/automation/req-9')
        self.assertEqual([], server.full)
        self.assertIn('cnb PR #12: success', printed)
        (issue,) = self.reused(server)
        self.assertEqual('success', reviews.result(reviews.scope('cnb', server.pull), issue, []))
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual('pending', reviews.result(reviews.scope('cnb', server.pull), issue, []))
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'another-key'}):
            self.assertEqual('pending', reviews.result(reviews.scope('cnb', server.pull), issue, []))

    def test_a_changed_line_gets_the_full_review(self):
        self.assert_full(self.scenario(self.repo.b2, self.repo.h3)[0])

    def test_a_block_or_missing_verdict_is_not_reused(self):
        for verdicts in (('pass', 'block'), ('pass',)):
            server, _, _ = self.scenario(self.repo.b2, self.repo.h2, verdicts=verdicts)
            self.assert_full(server, verdicts)
            self.assertNotEqual('success', server.github[self.repo.h2][reviews.CONTEXT]['state'])

    def test_a_later_block_on_the_same_patch_outweighs_an_earlier_pass(self):
        server = Server('github', {'number': '12', 'title': '改动', 'state': 'open', 'base': {'sha': self.repo.b1},
                                   'head': {'sha': self.repo.h1, 'ref': 'x'}})
        self.review(server, self.repo.b1, self.repo.h1, ('pass', 'pass'))
        # Red CI keeps the second commit of the same patch from reusing, so it gets, and fails, a full review.
        server.runs = [run('completed', 'failure')]
        self.review(server, self.repo.b1, self.repo.h1b, ('pass', 'block'))
        server.runs, server.full = [run('completed', 'success')], []
        self.move(server, self.repo.b2, self.repo.h2)
        self.assert_full(server)

    def test_a_reuse_always_names_the_round_that_was_actually_reviewed(self):
        # A reuse Issue is itself recorded as a pass; it must never become the source of the next reuse,
        # or the audit trail would point at a round no reviewer looked at.
        server, source, _ = self.scenario(self.repo.b2, self.repo.h2)
        self.move(server, self.repo.b3, self.repo.h5)
        self.assertEqual([], server.full)
        first, second = self.reused(server)
        for issue in (first, second):
            self.assertEqual(source['number'], json.loads(reviews.REUSE.search(issue['body'])[1])['payload']['source_issue'])

    def test_a_base_that_is_not_a_fast_forward_is_not_reused(self):
        self.assert_full(self.scenario(self.repo.side, self.repo.h4)[0])

    def test_unfinished_failed_or_stale_ci_is_not_reused(self):
        for ci in (('pending', 5), ('failure', 5), ('success', 90)):
            server, _, printed = self.scenario(self.repo.b2, self.repo.h2, platform='cnb', ci=ci)
            self.assertEqual([], self.reused(server), ci)
            self.assertNotIn('cnb PR #12: success', printed)
        server, _, printed = self.scenario(self.repo.b2, self.repo.h2, platform='cnb',
                                           ref='refs/heads/automation/req-9', ci=('pending', 5))
        self.assertEqual(([], []), (server.full, self.reused(server)))
        self.assertIn('waiting for CI', printed)

    def test_another_pulls_pass_is_not_reused(self):
        self.assert_full(self.scenario(self.repo.b2, self.repo.h2, source='13')[0])


if __name__ == '__main__':
    unittest.main()
