import contextlib
import io
import unittest
from unittest.mock import patch

import control
import reviews


def pull(number, head):
    return {'state': 'open', 'number': str(number), 'title': 'x', 'base': {'sha': 'a' * 40},
            'head': {'sha': head, 'ref': 'feature'}}


class Round:
    """Every open pull on one platform, each failing or passing as the test says; `broken` URLs return HTTP 500."""

    def __init__(self, github=(), cnb=(), broken=()):
        self.pulls = {reviews.GH: list(github), reviews.CNB: list(cnb)}
        self.broken = list(broken)
        self.gates = []
        self.handled = []

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        if any(part in url for part in self.broken):
            raise control.HttpStatusError(f'{method} returned HTTP 500: ', 500)
        if method == 'POST':
            self.gates.append((url.rsplit('/', 1)[-1], data['state']))
            return data
        if url.endswith('/status'):
            return {'statuses': []}
        for root, pulls in self.pulls.items():
            for item in pulls:
                if url == f'{root}/pulls/{item["number"]}':
                    return item
        raise AssertionError(f'unexpected request {method} {url}')

    def pages(self, url, page_key='page', size_key='page_size'):
        if any(part in url for part in self.broken):
            raise control.HttpStatusError('GET returned HTTP 500: ', 500)
        for root, pulls in self.pulls.items():
            if url.startswith(root) and '/pulls?' in url:
                return iter(pulls)
        return iter([])

    def run(self):
        printed = io.StringIO()

        def result(request, issue, comments, parts=None):
            self.handled.append(request['number'])
            return 'success'
        with (patch.object(reviews, 'api', side_effect=self.api), patch.object(reviews, 'pages', side_effect=self.pages),
              patch('security_finish.mirror_attestation', return_value=None),
              patch('security_finish.mirror_record', return_value=None),
              patch.object(reviews, 'ci_hold', return_value=(False, False)),
              patch.object(reviews, 'carry_over', return_value=None),
              patch.object(reviews, 'ensure_request', return_value={'number': '8', 'state': 'closed'}),
              patch.object(reviews, 'withhold'), patch.object(reviews, 'result', side_effect=result),
              patch.object(reviews, 'remember'), patch.object(reviews, 'shard_parts', return_value=None),
              patch.object(reviews, 'requirement_brief', return_value=''), contextlib.redirect_stdout(printed)):
            try:
                reviews.reconcile()
                return None, printed.getvalue()
            except reviews.RoundIncomplete as error:
                return error, printed.getvalue()


class ReconcileIsolationTests(unittest.TestCase):
    def test_a_clean_round_ends_without_an_error(self):
        error, _ = Round(github=[pull(1, 'b' * 40)]).run()
        self.assertIsNone(error)

    def test_one_pull_failing_leaves_the_rest_handled_and_the_round_red(self):
        server = Round(github=[pull(1, 'b' * 40), pull(2, 'c' * 40), pull(3, 'd' * 40)], cnb=[pull(4, 'e' * 40)],
                       broken=[f'{reviews.GH}/pulls/2'])
        error, printed = server.run()
        self.assertEqual(['1', '3', '4'], server.handled)
        self.assertEqual([('b' * 40, 'success'), ('d' * 40, 'success')], server.gates)
        self.assertIn('github PR #2', str(error))
        self.assertIn('HTTP 500', printed)

    def test_a_failed_pull_on_a_head_keeps_another_pulls_pass_off_the_gate(self):
        # The gate is the worst over every pull on a head, so one pull's pass cannot speak for the head alone.
        server = Round(github=[pull(1, 'b' * 40), pull(2, 'b' * 40)], broken=[f'{reviews.GH}/pulls/2'])
        error, _ = server.run()
        self.assertEqual(['1'], server.handled)
        self.assertEqual([], server.gates)
        self.assertIsNotNone(error)

    def test_a_gate_read_failing_does_not_stop_the_next_gate(self):
        # Run 41071290243: HTTP 500 reading one head's status, and the remaining gates were never written.
        server = Round(github=[pull(1, 'b' * 40), pull(2, 'c' * 40)], broken=[f'/commits/{"b" * 40}/status'])
        error, _ = server.run()
        self.assertEqual([('c' * 40, 'success')], server.gates)
        self.assertIn('gate of ' + 'b' * 12, str(error))

    def test_a_platform_list_failing_leaves_the_other_platform_handled(self):
        server = Round(github=[pull(1, 'b' * 40)], cnb=[pull(4, 'e' * 40)], broken=[f'{reviews.CNB}/pulls?'])
        error, _ = server.run()
        self.assertEqual(['1'], server.handled)
        self.assertEqual([('b' * 40, 'success')], server.gates)
        self.assertIn('cnb pull list', str(error))

    def test_a_review_that_cannot_be_closed_does_not_stop_the_round(self):
        server = Round(github=[pull(1, 'b' * 40)])
        request = reviews.scope('github', pull(9, 'f' * 40))
        issues = [{'number': '70', 'state': 'open'}, {'number': '71', 'state': 'open'}]
        closed = []

        def issue(number, missing=False):
            return {'number': number, 'state': 'open', 'body': number}

        def read(found):
            return request if found.get('number') in ('70', '71') else None

        def api(url, method='GET', data=None, missing=False, timeout=60):
            if url == f'{reviews.GH}/pulls/9':
                if not closed:
                    closed.append('first read')
                    raise control.HttpStatusError('GET returned HTTP 500: ', 500)
                return dict(pull(9, 'f' * 40), state='closed')
            if method == 'PATCH':
                closed.append(url)
                return {}
            return server.api(url, method, data, missing, timeout)

        def pages(url, page_key='page', size_key='page_size'):
            return iter(issues) if url.endswith('/issues?state=open') else server.pages(url)
        printed = io.StringIO()
        with (patch.object(reviews, 'api', side_effect=api), patch.object(reviews, 'pages', side_effect=pages),
              patch.object(reviews, '_issue', side_effect=issue), patch.object(reviews, 'request_from', side_effect=read),
              patch.object(reviews, '_reconcile_pull', side_effect=lambda p, l, r: server.handled.append(l['number'])),
              contextlib.redirect_stdout(printed), self.assertRaises(reviews.RoundIncomplete) as raised):
            reviews.reconcile()
        self.assertEqual(['first read', f'{reviews.CNB}/issues/71'], closed)
        self.assertEqual(['1'], server.handled)
        self.assertIn('closing finished reviews', str(raised.exception))


class ReconsiderHoldTests(unittest.TestCase):
    def reconsiders(self, ref, requirement):
        """How many times one pull's review reaches reconsider in a round, on the head branch `ref`."""
        item = dict(pull(1, 'b' * 40), head={'sha': 'b' * 40, 'ref': ref})
        server = Round(github=[item])
        read = []

        def pages(url, page_key='page', size_key='page_size'):
            if url.endswith('/comments') and '/issues/' in url and '/issues/8/' not in url:
                read.append(url)
                return iter(requirement)
            return server.pages(url)
        issue = {'number': '8', 'state': 'open'}
        with (patch.object(reviews, 'api', side_effect=server.api), patch.object(reviews, 'pages', side_effect=pages),
              patch('security_finish.mirror_attestation', return_value=None),
              patch('security_finish.mirror_record', return_value=None),
              patch.object(reviews, 'orphaned', return_value=False),
              patch.object(reviews, 'carry_over', return_value=issue), patch.object(reviews, 'withhold'),
              patch.object(reviews, 'result', return_value='failure'), patch.object(reviews, 'remember'),
              patch.object(reviews, 'shard_parts', return_value=None), patch.object(reviews, 'reconsider') as recheck,
              contextlib.redirect_stdout(io.StringIO())):
            reviews.reconcile()
        self.assertEqual([('b' * 40, 'failure')], server.gates)
        return recheck.call_count, read

    def test_a_held_requirement_gets_no_recheck_but_its_gate_is_still_written(self):
        owner = {'username': reviews.POLICY['approver'], 'is_npc': False}
        hold = {'created_at': '2026-10-30T01:00:00Z', 'body': 'HOLD', 'author': owner}
        release = {'created_at': '2026-10-30T02:00:00Z', 'body': 'RELEASE', 'author': owner}
        for ref in ('automation/req-291', 'refs/heads/automation/req-291'):
            self.assertEqual(0, self.reconsiders(ref, [hold])[0])
        self.assertEqual(1, self.reconsiders('automation/req-291', [hold, release])[0])

    def test_a_pull_that_is_not_a_requirement_reads_no_hold(self):
        self.assertEqual((1, []), self.reconsiders('fix/owner-branch', []))
