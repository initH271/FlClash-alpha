import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import reviews
from test_review_reuse import Server, checks
from test_review_snapshot import KEY, local_git, stamp


class ShardRepo:
    """A patch of two files, so one file per shard makes two groups, kept across two forward moves of the base."""

    def __init__(self, root):
        self.root, self.git = pathlib.Path(root), local_git(root)
        self.git('init', '-q')
        start = self.commit(None, {'m.txt': 'm1\n', 'a.txt': 'a1\n', 'b.txt': 'b1\n'})
        self.b1 = self.commit(start, {'m.txt': 'm2\n'})
        self.h1 = self.commit(self.b1, {'a.txt': 'A1\n', 'b.txt': 'B1\n'})
        self.b2 = self.commit(self.b1, {'m.txt': 'm3\n'})
        self.h2 = self.commit(self.b2, {'a.txt': 'A1\n', 'b.txt': 'B1\n'})
        self.b3 = self.commit(self.b2, {'m.txt': 'm4\n'})
        self.h3 = self.commit(self.b3, {'a.txt': 'A1\n', 'b.txt': 'B1\n'})

    def commit(self, parent, files):
        if parent:
            self.git('checkout', '-q', '--detach', parent)
        for name, text in files.items():
            (self.root / name).write_text(text)
        self.git('add', *files)
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                 'commit', '-q', '--no-verify', '-m', 'c')
        return self.git('rev-parse', 'HEAD')


class ShardServer(Server):
    """Server, plus what the real ensure_request and close_finished_reviews read and write."""

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        if method == 'PATCH':
            self.issues[url.rsplit('/', 1)[-1]].update(data)
            return {}
        if url.endswith('/issues') and method == 'POST':
            issue = self.add_issue(data['body'])
            issue['title'] = data['title']
            return issue
        return super().api(url, method, data, missing, timeout)

    def pages(self, url, page_key='page', size_key='page_size'):
        if '/issues?state=open' in url:
            return iter([i for i in self.issues.values() if i['state'] == 'open'])
        return super().pages(url, page_key, size_key)


class ShardReuseTests(unittest.TestCase):
    """Reuse of a round GLM passed through shards, over the real ensure_request and close_finished_reviews."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = ShardRepo(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        def evidence_git(*args, check=True, env=None):
            # The commits are already local; only the real fetch would reach the network.
            return '' if args[0] == 'fetch' else self.repo.git(*args, check=check, env=env)
        for item in (patch.dict(os.environ, KEY), patch.object(reviews, 'git', self.repo.git),
                     patch('review_evidence.git', evidence_git), patch.object(reviews, 'SHARD_FILES', 1)):
            item.start()
            self.addCleanup(item.stop)

    def run_pass(self, server):
        printed = io.StringIO()
        with (patch.object(reviews, 'api', side_effect=server.api),
              patch.object(reviews, 'pages', side_effect=server.pages),
              patch.object(reviews, 'all_issues', side_effect=lambda: list(server.issues.values())),
              patch.object(reviews, 'reconsider'), patch.object(reviews, 'requirement_brief', return_value=''),
              contextlib.redirect_stdout(printed)):
            reviews.reconcile()
        return printed.getvalue()

    def state(self, server, request):
        with (patch.object(reviews, 'api', side_effect=server.api),
              patch.object(reviews, 'pages', side_effect=server.pages),
              patch.object(reviews, 'all_issues', side_effect=lambda: list(server.issues.values()))):
            return reviews.state(request)

    def say(self, server, issue, request, role, verdict='pass'):
        if verdict == 'garbled':
            body = 'no machine line'
        else:
            body = 'FLCLASH_REVIEW ' + json.dumps({'request': reviews.identity(request), 'verdict': verdict,
                                                   'blockers': int(verdict != 'pass')})
        server.note(issue['number'], body, created=stamp(50),
                    author={'username': f'{reviews.POLICY["cnb"]}({role})', 'is_npc': True})

    def round(self, platform='github', ref='sync/x'):
        """Open the sharded review of h1 on b1, age it so later CI counts as newer, and return its pieces."""
        pull = {'number': '12', 'title': '改动', 'state': 'open', 'base': {'sha': self.repo.b1},
                'head': {'sha': self.repo.h1, 'ref': ref}, 'created_at': stamp(200)}
        server = ShardServer(platform, pull)
        server.statuses = checks('success', 90)
        self.run_pass(server)
        request = reviews.scope(platform, pull)
        main = next(i for i in server.issues.values() if reviews.request_from(i) == request)
        parts = self.shards(server, request)
        self.assertEqual(2, len(parts))
        for issue in server.issues.values():
            issue['created_at'] = stamp(60)
        return server, request, main, parts

    def shards(self, server, request):
        return [(reviews.request_from(i), i) for i in server.issues.values()
                if isinstance(reviews.request_from(i), dict) and reviews.request_from(i).get('shard')
                and reviews.unsharded(reviews.request_from(i)) == request]

    def passed(self, server, request, main, parts):
        """Both reviewers pass, GLM through its shards, and one controller run records that."""
        self.say(server, main, request, reviews.ROLES[0])
        for part, issue in parts:
            self.say(server, issue, part, reviews.GLM)
        self.run_pass(server)

    def move(self, server, base, head, ci=('success', 5)):
        server.pull.update(base={'sha': base}, head={'sha': head, 'ref': server.pull['head']['ref']})
        server.statuses = checks(*ci)
        return self.run_pass(server)

    def reused(self, server):
        return [i for i in server.issues.values() if '<!-- flclash-review-reuse ' in i['body']]

    def record(self, server, request, issue):
        return reviews._record(request, server.comments[issue['number']])

    def assert_full_review(self, server, base, head, label=None):
        request = dict(platform=server.platform, number='12', base=base, head=head)
        self.assertEqual([], self.reused(server), label)
        self.assertEqual(2, len(self.shards(server, request)), label)
        self.assertNotEqual('success', server.github[head][reviews.CONTEXT]['state'], label)

    def test_a_round_passed_through_shards_records_them(self):
        server, request, main, parts = self.round()
        self.passed(server, request, main, parts)
        self.assertEqual({'verdict': 'pass', 'glm_shards': sorted(i['number'] for _, i in parts)},
                         {k: v for k, v in self.record(server, request, main).items() if k != 'request'})

    def test_a_new_head_reuses_shards_without_opening_or_waiting_for_any(self):
        server, request, main, parts = self.round()
        self.passed(server, request, main, parts)
        self.move(server, self.repo.b2, self.repo.h2)

        # The superseded round closes first, and its closed shards still lend their recorded pass.
        self.assertEqual({'closed'}, {i['state'] for i in [main] + [i for _, i in parts]})
        new = reviews.scope('github', server.pull)
        self.assertEqual([], self.shards(server, new))
        (issue,) = self.reused(server)
        self.assertNotIn('flclash-review-shards', issue['body'])
        self.assertNotIn('@', issue['body'])
        payload = json.loads(reviews.REUSE.search(issue['body'])[1])['payload']
        self.assertEqual((main['number'], sorted(i['number'] for _, i in parts)),
                         (payload['source_issue'], payload['source_glm_shards']))
        self.assertEqual('success', server.github[self.repo.h2][reviews.CONTEXT]['state'])
        self.assertEqual('success', self.state(server, new))

        # The next run leaves it alone, and the next move still names the round reviewers saw.
        count = len(server.issues)
        self.run_pass(server)
        self.assertEqual((count, 'open'), (len(server.issues), issue['state']))
        self.assertEqual('success', server.github[self.repo.h2][reviews.CONTEXT]['state'])
        self.move(server, self.repo.b3, self.repo.h3)
        self.assertEqual('closed', issue['state'])
        self.assertEqual(count + 1, len(server.issues))
        latest = json.loads(reviews.REUSE.search(self.reused(server)[-1]['body'])[1])['payload']
        self.assertEqual(main['number'], latest['source_issue'])
        self.assertEqual('success', server.github[self.repo.h3][reviews.CONTEXT]['state'])

    def test_a_cnb_round_passed_through_shards_is_reused_after_fresh_ci(self):
        server, request, main, parts = self.round('cnb', 'refs/heads/feature')
        self.passed(server, request, main, parts)
        printed = self.move(server, self.repo.b2, self.repo.h2)
        self.assertEqual(1, len(self.reused(server)))
        self.assertEqual([], self.shards(server, reviews.scope('cnb', server.pull)))
        self.assertIn('cnb PR #12: success', printed)

    def test_a_block_on_any_shard_is_recorded_as_a_block_and_not_reused(self):
        for verdict in ('block', 'garbled'):
            server, request, main, parts = self.round()
            self.say(server, main, request, reviews.ROLES[0])
            self.say(server, parts[0][1], parts[0][0], reviews.GLM)
            self.say(server, parts[1][1], parts[1][0], reviews.GLM, verdict)
            self.run_pass(server)
            self.assertEqual('block', self.record(server, request, main)['verdict'], verdict)
            self.move(server, self.repo.b2, self.repo.h2)
            self.assert_full_review(server, self.repo.b2, self.repo.h2, verdict)

    def test_a_block_posted_after_the_recorded_pass_is_not_reused(self):
        for target, verdict in (('shard', 'block'), ('shard', 'garbled'), ('main', 'block')):
            label = (target, verdict)
            server, request, main, parts = self.round()
            self.passed(server, request, main, parts)
            self.assertEqual('pass', self.record(server, request, main)['verdict'], label)
            if target == 'shard':
                self.say(server, parts[0][1], parts[0][0], reviews.GLM, verdict)
            else:
                self.say(server, main, request, reviews.ROLES[0], verdict)
            # No run saw it before the head moved, so the record still says pass.
            self.move(server, self.repo.b2, self.repo.h2)
            self.assertEqual('pass', self.record(server, request, main)['verdict'], label)
            self.assert_full_review(server, self.repo.b2, self.repo.h2, label)

    def test_a_corrected_shard_block_can_be_reused(self):
        server, request, main, parts = self.round()
        self.say(server, parts[0][1], parts[0][0], reviews.GLM, 'block')
        self.run_pass(server)
        self.assertEqual('block', self.record(server, request, main)['verdict'])
        self.passed(server, request, main, parts)
        self.assertEqual('pass', self.record(server, request, main)['verdict'])
        self.move(server, self.repo.b2, self.repo.h2)
        self.assertEqual(1, len(self.reused(server)))

    def test_shard_passes_no_run_recorded_before_the_head_moved_are_not_reused(self):
        server, request, main, parts = self.round()
        self.say(server, main, request, reviews.ROLES[0])
        for part, issue in parts:
            self.say(server, issue, part, reviews.GLM)
        self.move(server, self.repo.b2, self.repo.h2)
        self.assertIsNone(self.record(server, request, main))
        self.assert_full_review(server, self.repo.b2, self.repo.h2)

    def test_a_recorded_shard_that_no_longer_reads_back_is_not_reused(self):
        server, request, main, parts = self.round()
        self.passed(server, request, main, parts)
        parts[0][1]['body'] = 'edited, so its signed record is gone'
        self.move(server, self.repo.b2, self.repo.h2)
        self.assert_full_review(server, self.repo.b2, self.repo.h2)

    def test_a_pass_recorded_without_the_shards_it_rests_on_is_not_reused(self):
        server, request, main, parts = self.round()
        self.say(server, main, request, reviews.ROLES[0])
        server.note(main['number'], '<!-- flclash-review-snapshot ' + json.dumps(reviews.sign(
            {'request': reviews.identity(request), 'verdict': 'pass'})) + ' -->', created=stamp(40))
        self.move(server, self.repo.b2, self.repo.h2)
        self.assert_full_review(server, self.repo.b2, self.repo.h2)

    def test_a_glm_report_on_the_main_issue_of_a_sharded_round_is_ignored_as_the_gate_ignores_it(self):
        server, request, main, parts = self.round()
        self.passed(server, request, main, parts)
        self.say(server, main, request, reviews.GLM, 'block')
        self.run_pass(server)
        self.assertEqual('pass', self.record(server, request, main)['verdict'])
        self.move(server, self.repo.b2, self.repo.h2)
        self.assertEqual(1, len(self.reused(server)))

    def test_an_unsharded_round_records_no_shards(self):
        with patch.object(reviews, 'SHARD_FILES', 6):
            pull = {'number': '12', 'title': '改动', 'state': 'open', 'base': {'sha': self.repo.b1},
                    'head': {'sha': self.repo.h1, 'ref': 'sync/x'}, 'created_at': stamp(200)}
            server = ShardServer('github', pull)
            self.run_pass(server)
            request = reviews.scope('github', pull)
            (main,) = server.issues.values()
            main['created_at'] = stamp(60)
            for role in reviews.ROLES:
                self.say(server, main, request, role)
            self.run_pass(server)
            self.assertNotIn('glm_shards', self.record(server, request, main))
            self.move(server, self.repo.b2, self.repo.h2)
            (issue,) = self.reused(server)
            self.assertNotIn('source_glm_shards', json.loads(reviews.REUSE.search(issue['body'])[1])['payload'])


if __name__ == '__main__':
    unittest.main()
