import os
import pathlib
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import reviews
from test_review_reuse import ReuseTests, Server, checks, run
from test_review_snapshot import KEY, Repo, local_git, stamp


class DatedRepo(Repo):
    """The same history as Repo, with every commit dated `offset` seconds from now."""

    def __init__(self, root, offset):
        self.offset = offset
        super().__init__(root)

    def commit(self, parent, files, message='c'):
        if parent:
            self.git('checkout', '-q', '--detach', parent)
        for name, text in files.items():
            (self.root / name).write_text(text)
        self.git('add', *files)
        when = f'@{int(time.time() + self.offset)} +0000'
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                 'commit', '-q', '--no-verify', '-m', message,
                 env=dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when))
        return self.git('rev-parse', 'HEAD')


class Base(unittest.TestCase):
    """One round passed on b1, so the pull's head can then move; ReuseTests' harness over the HTTP layer."""

    run_pass, move, review, scenario, reused, assert_full = (
        ReuseTests.run_pass, ReuseTests.move, ReuseTests.review, ReuseTests.scenario, ReuseTests.reused,
        ReuseTests.assert_full)
    offset = 0

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = DatedRepo(cls.tmp.name, cls.offset)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        for item in (patch.dict(os.environ, KEY), patch.object(reviews, 'git', self.repo.git)):
            item.start()
            self.addCleanup(item.stop)

    def reviewed(self, platform='github', ref='sync/x'):
        pull = {'number': '12', 'title': '改动', 'state': 'open', 'base': {'sha': self.repo.b1},
                'head': {'sha': self.repo.h1, 'ref': ref}, 'created_at': stamp(200)}
        server = Server(platform, pull)
        self.review(server, self.repo.b1, self.repo.h1, ('pass', 'pass'))
        server.full.clear()
        return server

    def assert_untouched(self, server, head, before, printed):
        """Nothing opened, nothing commented, no status on the head: the required gate stays pending."""
        self.assertEqual((before, []), ((len(server.issues), sum(map(len, server.pulls.values()))), server.full))
        self.assertNotIn(head, server.github)
        self.assertIn('waiting for CI', printed)

    def size(self, server):
        return len(server.issues), sum(map(len, server.pulls.values()))


class WaitTests(Base):
    def waits(self, server, ci=('success', 5)):
        before = self.size(server)
        printed = self.move(server, self.repo.b2, self.repo.h2, ci)
        self.assert_untouched(server, self.repo.h2, before, printed)

    def test_same_patch_with_github_ci_running_opens_and_writes_nothing_then_reuses(self):
        server = self.reviewed()
        server.runs = [run('completed', 'success'), run('in_progress')]
        self.waits(server)
        server.runs = [run('completed', 'success')]
        self.run_pass(server)
        self.assertEqual(([], 1), (server.full, len(self.reused(server))))
        self.assertEqual('success', server.github[self.repo.h2][reviews.CONTEXT]['state'])

    def test_same_patch_with_cnb_ci_running_opens_and_writes_nothing_then_reuses(self):
        server = self.reviewed('cnb', 'refs/heads/feature')
        self.waits(server, ('pending', 5))
        server.statuses = checks('success', 1)
        printed = self.run_pass(server)
        self.assertEqual(([], 1), (server.full, len(self.reused(server))))
        self.assertIn('cnb PR #12: success', printed)

    def test_cnb_passes_older_than_the_round_or_no_pipeline_at_all_are_not_a_verdict_yet(self):
        for statuses in (checks('success', 90), {'statuses': []}):
            server = self.reviewed('cnb', 'refs/heads/feature')
            before = self.size(server)
            server.pull.update(base={'sha': self.repo.b2}, head={'sha': self.repo.h2, 'ref': 'refs/heads/feature'})
            for issue in server.issues.values():
                issue['state'] = 'closed'
            server.statuses = statuses
            self.assert_untouched(server, self.repo.h2, before, self.run_pass(server))

    def test_github_head_with_no_check_besides_the_gate_waits(self):
        server = self.reviewed()
        server.runs, server.extra = [run('completed', 'skipped')], [{'context': reviews.CONTEXT, 'state': 'pending'}]
        self.waits(server)

    def test_the_controllers_own_running_job_does_not_hold_or_satisfy_reuse(self):
        # The shape of a real head: this job is in progress while it reads the list.
        own = {'name': reviews.CONTROLLER_CHECK, 'status': 'in_progress', 'conclusion': None}
        server = self.reviewed()
        server.runs = [own, {'name': 'track', 'status': 'completed', 'conclusion': 'skipped'},
                       {'name': 'Dependency vulnerability scan', 'status': 'completed', 'conclusion': 'success'}]
        self.move(server, self.repo.b2, self.repo.h2)
        self.assertEqual(([], 1), (server.full, len(self.reused(server))))
        server = self.reviewed()
        server.runs = [dict(own, status='completed', conclusion='success')]
        self.waits(server)

    def test_the_excluded_check_is_the_job_in_the_review_workflow(self):
        workflow = pathlib.Path(reviews.__file__).parent.parent / '.github/workflows/reviews.yaml'
        self.assertRegex(workflow.read_text(), rf'(?m)^jobs:\n  {reviews.CONTROLLER_CHECK}:$')


class VerdictTests(Base):
    def test_same_patch_with_every_check_passed_reuses_at_once(self):
        for platform, ref in (('github', 'sync/x'), ('cnb', 'refs/heads/feature')):
            server = self.reviewed(platform, ref)
            self.move(server, self.repo.b2, self.repo.h2)
            self.assertEqual(([], 1), (server.full, len(self.reused(server))), platform)

    def test_same_patch_with_finished_failed_ci_gets_the_full_review(self):
        server = self.reviewed()
        server.runs = [run('completed', 'failure')]
        printed = self.move(server, self.repo.b2, self.repo.h2)
        self.assert_full(server)
        self.assertIn('CI failed', printed)
        server = self.reviewed('cnb', 'refs/heads/feature')
        printed = self.move(server, self.repo.b2, self.repo.h2, ('failure', 5))
        self.assert_full(server)
        self.assertIn('CI failed', printed)

    def test_a_failure_while_another_check_runs_waits_for_the_end_then_reviews(self):
        server = self.reviewed()
        server.runs = [run('completed', 'failure'), run('in_progress')]
        before = self.size(server)
        self.assert_untouched(server, self.repo.h2, before, self.move(server, self.repo.b2, self.repo.h2))
        server.runs = [run('completed', 'failure'), run('completed', 'success')]
        self.run_pass(server)
        self.assert_full(server)

    def test_a_different_patch_never_waits(self):
        server = self.reviewed()
        server.runs = [run('in_progress')]
        printed = self.move(server, self.repo.b2, self.repo.h3)
        self.assert_full(server)
        self.assertNotIn('waiting for CI', printed)
        server = self.reviewed('cnb', 'refs/heads/feature')
        self.assertNotIn('waiting for CI', self.move(server, self.repo.b2, self.repo.h3, ('pending', 5)))
        self.assert_full(server)

    def test_a_requirement_branch_keeps_ci_hold_and_its_lateness_ends_the_wait(self):
        ref = 'refs/heads/automation/req-9'
        server = self.reviewed('cnb', ref)
        printed = self.move(server, self.repo.b2, self.repo.h2, ('pending', 5))
        self.assertEqual(([], []), (server.full, self.reused(server)))
        self.assertIn('cnb PR #12: waiting for CI', printed)
        self.assertNotIn('same patch', printed)
        server = self.reviewed('cnb', ref)
        printed = self.move(server, self.repo.b2, self.repo.h2, ('pending', 90))
        self.assert_full(server)
        self.assertIn('wait limit', printed)


class PastLimitTests(Base):
    offset = -(reviews.CI_GRACE_SECONDS + 60)

    def test_ci_unsettled_past_the_limit_gets_the_full_review_and_a_log_line(self):
        for label, runs in (('running', [run('in_progress')]), ('no record', [])):
            server = self.reviewed()
            server.runs = runs
            printed = self.move(server, self.repo.b2, self.repo.h2)
            self.assert_full(server, label)
            self.assertIn('wait limit', printed, label)
        server = self.reviewed('cnb', 'refs/heads/feature')
        printed = self.move(server, self.repo.b2, self.repo.h2, ('pending', 5))
        self.assert_full(server)
        self.assertIn('wait limit', printed)

    def test_ci_that_passed_is_still_reused_past_the_limit(self):
        server = self.reviewed()
        self.move(server, self.repo.b2, self.repo.h2)
        self.assertEqual(([], 1), (server.full, len(self.reused(server))))


class JustUnderLimitTests(Base):
    offset = -(reviews.CI_GRACE_SECONDS - 300)

    def test_ci_unsettled_under_the_limit_still_waits(self):
        server = self.reviewed()
        server.runs = [run('in_progress')]
        before = self.size(server)
        self.assert_untouched(server, self.repo.h2, before, self.move(server, self.repo.b2, self.repo.h2))


class FutureCommitTests(Base):
    offset = 86400

    def test_a_commit_dated_in_the_future_cannot_extend_the_wait(self):
        server = self.reviewed()
        server.runs = [run('in_progress')]
        printed = self.move(server, self.repo.b2, self.repo.h2)
        self.assert_full(server)
        self.assertIn('wait limit', printed)


class FetchTests(Base):
    """The controller's checkout holds only main until the remote answers a fetch by sha.

    The answer goes through a git alternate rather than a real fetch, which the no-network guard rightly stops.
    """

    def setUp(self):
        super().setUp()
        self.checkout = tempfile.TemporaryDirectory()
        self.addCleanup(self.checkout.cleanup)
        self.local = local_git(self.checkout.name)
        self.local('init', '-q')
        self.repo.git('update-ref', 'refs/heads/main-only', self.repo.b2)
        bundle = pathlib.Path(self.checkout.name) / 'main.bundle'
        self.repo.git('bundle', 'create', str(bundle), 'refs/heads/main-only')
        self.local('bundle', 'unbundle', str(bundle))
        self.fetched, self.answer = [], 0

    def controller_git(self, *args, check=True, env=None):
        if args[0] != 'fetch':
            return self.local(*args, check=check, env=env)
        self.fetched.append(args)
        if not self.answer:
            alternates = pathlib.Path(self.checkout.name) / '.git/objects/info/alternates'
            alternates.parent.mkdir(parents=True, exist_ok=True)
            alternates.write_text(str(self.repo.root / '.git/objects') + '\n')
        return subprocess.CompletedProcess(['git', *args], self.answer, stdout='', stderr='')

    def moved(self, platform='github', ref='sync/x'):
        server = self.reviewed(platform, ref)
        with patch.object(reviews, 'git', self.controller_git):
            printed = self.move(server, self.repo.b2, self.repo.h2)
        return server, printed

    def test_the_old_head_and_new_head_are_fetched_and_the_reuse_hits(self):
        for platform, ref, url in (('github', 'sync/x', f'https://github.com/{reviews.POLICY["github"]}.git'),
                                   ('cnb', 'refs/heads/feature', f'https://cnb.cool/{reviews.POLICY["cnb"]}.git')):
            alternates = pathlib.Path(self.checkout.name) / '.git/objects/info/alternates'
            alternates.unlink(missing_ok=True)
            self.fetched.clear()
            server, _ = self.moved(platform, ref)
            self.assertEqual(([], 1), (server.full, len(self.reused(server))), platform)
            (fetch,) = self.fetched
            self.assertEqual(url, fetch[2])
            self.assertIn(self.repo.h1, fetch)
            self.assertIn(self.repo.h2, fetch)
            self.assertNotIn(self.repo.b2, fetch)

    def test_a_failed_fetch_falls_back_to_the_full_review_and_says_so(self):
        self.answer = 128
        server, printed = self.moved()
        self.assert_full(server)
        self.assertIn('could not fetch', printed)
        self.assertNotIn('waiting for CI', printed)


if __name__ == '__main__':
    unittest.main()
