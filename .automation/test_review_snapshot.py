import json
import os
import pathlib
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import reviews

KEY = {'UPSTREAM_APPROVAL_KEY': 'test-key'}


def stamp(minutes):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - minutes * 60))


def local_git(root):
    """Same signature and return types as control.git, run in a throwaway repository."""
    def git(*args, check=True, env=None):
        found = subprocess.run(['git', *args], cwd=root, env=env, text=True, capture_output=True, check=False)
        if check and found.returncode:
            raise RuntimeError(f'git {args[0]} failed: {found.stderr[-1500:]}')
        return found.stdout.strip() if check else found
    return git


class Repo:
    """Bases that move forward b1 -> b2 -> b3 with the same patch on each, a changed patch and an unrelated base."""

    def __init__(self, root):
        self.root, self.git = pathlib.Path(root), local_git(root)
        self.git('init', '-q')
        self.root_commit = self.commit(None, {'m.txt': 'm1\n', 'p.txt': 'p1\np2\np3\n'})
        self.b1 = self.commit(self.root_commit, {'m.txt': 'm1\nm2\n'})
        self.h1 = self.commit(self.b1, {'p.txt': 'p1\nP2\np3\n'})
        self.h1b = self.commit(self.b1, {'p.txt': 'p1\nP2\np3\n'}, 'same patch, another commit')
        self.b2 = self.commit(self.b1, {'m.txt': 'm1\nm2\nm3\n'})
        self.h2 = self.commit(self.b2, {'p.txt': 'p1\nP2\np3\n'})
        self.h3 = self.commit(self.b2, {'p.txt': 'p1\nP2\nP3\n'})
        self.b3 = self.commit(self.b2, {'m.txt': 'm1\nm2\nm3\nm4\n'})
        self.h5 = self.commit(self.b3, {'p.txt': 'p1\nP2\np3\n'})
        self.side = self.commit(self.root_commit, {'m.txt': 'x\n'})
        self.h4 = self.commit(self.side, {'p.txt': 'p1\nP2\np3\n'})

    def commit(self, parent, files, message='c'):
        if parent:
            self.git('checkout', '-q', '--detach', parent)
        for name, text in files.items():
            (self.root / name).write_text(text)
        self.git('add', *files)
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
                 'commit', '-q', '--no-verify', '-m', message)
        return self.git('rev-parse', 'HEAD')


class PatchIdTests(unittest.TestCase):
    def test_patch_id_survives_a_rebase_that_changes_the_tree(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Repo(root)
            with patch.object(reviews, 'git', repo.git):
                self.assertNotEqual(repo.git('rev-parse', repo.h1 + '^{tree}'), repo.git('rev-parse', repo.h2 + '^{tree}'))
                first = reviews.patch_id(repo.b1, repo.h1)
                self.assertRegex(first, r'^[0-9a-f]{40}$')
                self.assertEqual(first, reviews.patch_id(repo.b2, repo.h2))
                self.assertNotEqual(first, reviews.patch_id(repo.b2, repo.h3))
                self.assertIsNone(reviews.patch_id(repo.b1, repo.b1))
                self.assertIsNone(reviews.patch_id(repo.b1, 'f' * 40))


class SnapshotTests(unittest.TestCase):
    request = {'platform': 'github', 'number': '1', 'base': 'a' * 40, 'head': 'b' * 40}
    issue = {'number': '42', 'state': 'open', 'created_at': '2026-09-20T00:00:00Z'}

    def setUp(self):
        env = patch.dict(os.environ, KEY)
        env.start()
        self.addCleanup(env.stop)

    def report(self, role, verdict):
        body = json.dumps({'request': reviews.identity(self.request), 'verdict': verdict,
                           'blockers': 0 if verdict == 'pass' else 1})
        return {'author': {'username': f'{reviews.POLICY["cnb"]}({role})', 'is_npc': True},
                'created_at': '2026-09-20T00:01:00Z', 'id': '1', 'body': 'FLCLASH_REVIEW ' + body}

    def owner(self, body, n=9):
        return {'author': {'username': reviews.POLICY['approver'], 'is_npc': False},
                'created_at': f'2026-09-20T00:0{n}:00Z', 'id': str(n), 'body': body}

    def snap(self, verdict):
        payload = {'request': reviews.identity(self.request), 'verdict': verdict}
        return self.owner('<!-- flclash-review-snapshot ' + json.dumps(reviews.sign(payload)) + ' -->')

    def test_snapshots_never_change_the_gate_result(self):
        cases = {'success': reviews.ROLES, 'failure': reviews.ROLES[:1], 'pending': reviews.ROLES[1:]}
        for expected, passing in cases.items():
            reports = [self.report(role, 'pass' if role in passing else 'block') for role in reviews.ROLES]
            if expected == 'pending':
                reports = reports[1:]
            for verdict in ('pass', 'block'):
                self.assertEqual(expected, reviews.result(self.request, self.issue, reports + [self.snap(verdict)]))

    def test_remember_records_each_change_once(self):
        comments = []
        with patch.object(reviews, 'api') as api:
            for status, posted in (('pending', None), ('success', 'pass'), ('success', None),
                                   ('pending', 'block'), ('failure', None), ('success', 'pass')):
                api.reset_mock()
                reviews.remember(self.request, self.issue, comments, status)
                if posted is None:
                    api.assert_not_called()
                    continue
                url, method, data = api.call_args.args
                self.assertEqual((f'{reviews.CNB}/issues/42/comments', 'POST'), (url, method))
                comments.append(self.owner(data['body'], len(comments) + 1))
                self.assertEqual(posted, reviews.snapshot(self.request, comments))
        other = dict(self.request, head='c' * 40)
        self.assertIsNone(reviews.snapshot(other, comments))
        forged = dict(self.snap('pass'), author={'username': reviews.POLICY['approver'], 'is_npc': True})
        self.assertIsNone(reviews.snapshot(self.request, [forged]))


if __name__ == '__main__':
    unittest.main()
