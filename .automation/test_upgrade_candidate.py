import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import control
import reviews

OWNER = {'username': control.POLICY['approver'], 'is_npc': False}
GH_PR = 'https://github.com/example/pull/5'


class UpgradeRepo(unittest.TestCase):
    """A real local repository; only git transport and the HTTP APIs are replaced."""

    def setUp(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        self.root = pathlib.Path(directory)
        for item in (patch.object(control, 'ROOT', self.root),
                     patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'unit-test-key', 'CNB_AUTOMATION_TOKEN': 'unit'}),
                     patch.object(control, 'git', self.git), patch.object(control, 'api', self.api),
                     patch.object(control, 'pages', self.pages), patch.object(reviews, 'api', self.api),
                     patch.object(reviews, 'pages', self.pages)):
            item.start()
            self.addCleanup(item.stop)
        self.remote, self.pushed, self.calls, self.comments = {}, [], [], []
        self.issue_state, self.gh_pulls, self.review_issue, self.release, self.issue_error = 'open', [], None, None, None
        self.real('init', '-q', '-b', 'main')
        self.real('config', 'user.name', 'Test')
        self.real('config', 'user.email', 'test@example.invalid')
        for name in ('.github/release.json', '.automation/policy.json'):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(pathlib.Path(control.__file__).parents[1] / name, self.root / name)
        self.base = self.commit('app.txt', 'base\n', 'base')

    def real(self, *args, check=True, env=None):
        result = subprocess.run(['git', *args], cwd=self.root, env=env, text=True,
                                capture_output=True, check=False)
        if check and result.returncode:
            raise RuntimeError(f'git {args[0]} failed: {result.stderr[-1500:]}')
        return result.stdout.strip() if check else result

    def git(self, *args, check=True, env=None):
        if args[0] == 'fetch':
            if args[1] == 'origin':
                self.real('update-ref', 'refs/remotes/origin/' + args[2], self.remote[args[2]])
                (self.root / '.git/FETCH_HEAD').write_text(self.remote[args[2]] + '\n')
            return '' if check else subprocess.CompletedProcess(args, 0, '', '')
        if args[0] == 'push':
            source, _, target = args[-1].partition(':')
            self.pushed.append((args[1], target or source, self.real('rev-parse', source)))
            if args[1] == 'origin':
                self.remote[(target or source).removeprefix('refs/heads/')] = self.real('rev-parse', source)
            return '' if check else subprocess.CompletedProcess(args, 0, '', '')
        return self.real(*args, check=check, env=env)

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        self.calls.append((method, url, data))
        if url.endswith('/comments') and method == 'POST':
            self.comments.append({'author': OWNER, 'body': data['body'], 'work_mode': data['work_mode']})
            return {}
        if url.endswith('/git/ref/heads/main'):
            return {'object': {'sha': self.remote['main']}}
        if '/pulls?state=open&head=' in url:
            return [{'number': 5, 'html_url': GH_PR}] if any(c[0] == 'POST' and c[1].endswith('/pulls') for c in self.calls) else []
        if url.endswith('/pulls') and method == 'POST':
            return {'number': 5, 'html_url': GH_PR}
        if url.endswith('/pulls/5'):
            return self.gh_pulls[0]
        if '/releases/tags/' in url:
            return self.release
        if '/git/ref/tags/' in url:
            return {'object': {'type': 'commit', 'sha': self.request['sha']}}
        if url.endswith('/issues/217') and self.issue_error:
            raise control.HttpStatusError('GET api.cnb.cool returned HTTP 502: ', 502)
        if url.endswith('/issues/217'):
            if method == 'PATCH':
                self.issue_state = data['state']
                return {}
            return {'state': self.issue_state, 'body': control.marker(self.request)}
        if url.endswith('/issues/300'):
            return self.review_issue
        if 'workflows/build.yaml/runs' in url:
            return {'workflow_runs': []}
        if '/statuses/' in url or url.endswith('/status'):
            return {'statuses': []}
        if url.endswith('/dispatches') or url.endswith('/build/start'):
            return None
        self.fail(f'Unexpected API call: {method} {url}')

    def pages(self, url, page_key='page', size_key='page_size'):
        if url.endswith('/issues/217/comments'):
            return [{'author': OWNER, 'body': 'OK'}] + list(self.comments)
        if url.endswith('/issues/300/comments'):
            return self.review_reports
        if '/issues?state=open' in url and self.review_issue:
            return [{'number': 300}]
        if url.startswith(control.GH) and '/pulls?state=open' in url:
            return self.gh_pulls
        return []

    def commit(self, name, text, message):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.real('add', '-A')
        self.real('commit', '-q', '-m', message)
        return self.real('rev-parse', 'HEAD')

    def upstream(self):
        """An upstream release commit built on the shared base: it edits app.txt and a protected path."""
        self.real('checkout', '-q', '-b', 'upstream', self.base)
        self.commit('.github/upstream.yml', 'ci\n', 'upstream ci')
        sha = self.commit('app.txt', 'upstream\n', 'upstream app')
        self.request = {'tag': 'v9.9.9', 'sha': sha, 'upstream': control.POLICY['upstream']}
        self.real('checkout', '-q', 'main')
        return sha

    def owner_comments(self):
        return [c for c in self.comments if 'flclash-owner-merge' in c['body']]


class ConflictHandoffTests(UpgradeRepo):
    def test_conflict_asks_owner_once_and_never_summons_the_developer(self):
        upstream = self.upstream()
        self.remote['main'] = self.commit('app.txt', 'personal\n', 'personal change')
        branch = 'automation/upstream-v9.9.9'
        for _ in range(2):
            control.prepare_candidate(self.request, 217, branch)
        self.assertEqual(1, len(self.comments), self.comments)
        body = self.comments[0]['body']
        self.assertEqual(1, len(self.owner_comments()))
        self.assertNotIn('@', body)
        self.assertFalse(self.comments[0]['work_mode'])
        for text in ('1 个冲突文件和 1 个受保护文件', '- `app.txt`', '- `.github/upstream.yml`', upstream,
                     '需要 owner 人工合并上游', '回复 OK，控制器会在升级分支', GH_PR, 'AUTOMATION.md 上游升级一节（待补）'):
            self.assertIn(text, body)
        tree = self.real('ls-tree', '-r', '--name-only', self.remote[branch]).splitlines()
        self.assertIn('UPSTREAM_REVIEW.md', tree)
        self.assertEqual('personal', self.real('show', f'{self.remote[branch]}:app.txt'))

    def test_owner_merge_listing_is_capped(self):
        self.assertIn('另有 2 个未列出', control.listed([f'f{i}' for i in range(12)]))
        self.assertNotIn('f10', control.listed([f'f{i}' for i in range(12)]))


class UpstreamAlreadyInMainTests(UpgradeRepo):
    def test_owner_merged_upstream_prepares_without_merging_again_and_reaches_dispatch(self):
        upstream = self.upstream()
        self.commit('personal.txt', 'mine\n', 'personal change')
        self.real('merge', '-q', '--no-ff', '-X', 'theirs', '-m', 'owner merges upstream', upstream)
        main = self.remote['main'] = self.real('rev-parse', 'HEAD')
        branch = 'automation/upstream-v9.9.9'
        control.prepare_candidate(self.request, 217, branch)
        head = self.remote[branch]
        self.assertEqual([main], self.real('rev-list', '--parents', '-n1', head).split()[1:])
        self.assertEqual(['.automation/candidate.json', '.automation/policy.json', '.github/release-notes.md',
                          '.github/release.json'], self.real('diff', '--name-only', main, head).splitlines())
        candidate = control.verify(json.loads(self.real('show', f'{head}:.automation/candidate.json')))
        self.assertEqual({'issue': '217', 'base': main, 'tree': control.source_tree(), 'upstream_sha': upstream}, candidate)
        self.assertEqual(upstream, json.loads((self.root / '.automation/policy.json').read_text())['upstream_sha'])
        self.assertEqual([], self.owner_comments())
        self.assertIn('已按本次 OK 批准', self.comments[-1]['body'])

        request = {'platform': 'github', 'number': '5', 'base': main, 'head': head}
        self.gh_pulls = [{'number': 5, 'state': 'open', 'title': 't', 'draft': True, 'body': '',
                          'base': {'sha': main, 'ref': 'main'}, 'head': {'sha': head, 'ref': branch}}]
        self.review_issue = {'number': 300, 'state': 'open', 'created_at': '1', 'author': OWNER,
                             'title': reviews.review_title(request, 't'),
                             'body': '<!-- flclash-pr-review ' + json.dumps(control.sign(request)) + ' -->'}
        report = 'FLCLASH_REVIEW ' + json.dumps({'request': reviews.identity(request), 'verdict': 'pass', 'blockers': 0})
        self.review_reports = [{'author': {'username': f'{control.POLICY["cnb"]}({r})', 'is_npc': True},
                                'id': str(i), 'created_at': '2', 'body': report} for i, r in enumerate(reviews.ROLES)]
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            control.resume_candidate(head, branch, 217)
        self.assertNotIn('invalid', printed.getvalue())
        dispatched = [c for c in self.calls if c[1].endswith('/dispatches')]
        self.assertEqual(head, dispatched[0][2]['inputs']['source_ref'])

    def test_prepare_overwrites_a_stale_candidate_left_on_main(self):
        stale = {'issue': '200', 'base': self.base, 'tree': 'f' * 40, 'upstream_sha': 'a' * 40}
        self.commit('.automation/candidate.json', json.dumps(control.sign(stale)), 'finished candidate')
        upstream = self.upstream()
        self.real('merge', '-q', '--no-ff', '-X', 'theirs', '-m', 'owner merges upstream', upstream)
        self.remote['main'] = self.real('rev-parse', 'HEAD')
        control.prepare_candidate(self.request, 217, 'automation/upstream-v9.9.9')
        head = self.remote['automation/upstream-v9.9.9']
        candidate = control.verify(json.loads(self.real('show', f'{head}:.automation/candidate.json')))
        self.assertEqual(('217', upstream), (candidate['issue'], candidate['upstream_sha']))

    def test_conflict_branch_is_adopted_once_the_owner_merges_upstream(self):
        upstream = self.upstream()
        self.remote['main'] = self.commit('app.txt', 'personal\n', 'personal change')
        branch = 'automation/upstream-v9.9.9'
        control.prepare_candidate(self.request, 217, branch)
        conflict = self.remote[branch]
        self.real('checkout', '-q', 'main')
        self.real('merge', '-q', '--no-ff', '-X', 'theirs', '-m', 'owner merges upstream', upstream)
        main = self.remote['main'] = self.real('rev-parse', 'HEAD')
        with contextlib.redirect_stdout(io.StringIO()):
            control.resume_candidate(conflict, branch, 217)
        head = self.remote[branch]
        self.assertEqual([conflict, main], self.real('rev-list', '--parents', '-n1', head).split()[1:])
        candidate = control.verify(json.loads(self.real('show', f'{head}:.automation/candidate.json')))
        self.assertEqual((main, upstream), (candidate['base'], candidate['upstream_sha']))
        self.assertNotIn('UPSTREAM_REVIEW.md', self.real('ls-tree', '-r', '--name-only', head).splitlines())
        self.assertEqual(1, len(self.owner_comments()))
        self.assertIn('已按本次 OK 批准', self.comments[-1]['body'])


class FinishedCandidateTests(UpgradeRepo):
    def promoted(self):
        upstream = self.upstream()
        self.real('merge', '-q', '--no-ff', '-X', 'theirs', '-m', 'upstream', upstream)
        metadata = control.next_release(json.loads((self.root / '.github/release.json').read_text()), upstream='9.9.9')
        (self.root / '.github/release.json').write_text(json.dumps(metadata))
        self.candidate = {'issue': '217', 'base': self.base, 'tree': control.source_tree(), 'upstream_sha': upstream}
        self.commit('.automation/candidate.json', json.dumps(control.sign(self.candidate)), 'candidate')
        self.remote['main'] = head = self.real('rev-parse', 'HEAD')
        return head

    def test_closed_issue_finishes_the_candidate(self):
        self.promoted()
        self.issue_state = 'closed'
        self.assertIsNone(control.active_candidate())
        self.assertIsNone(control.active_candidate(released=True))

    def test_published_release_of_the_merged_upstream_finishes_the_candidate(self):
        self.promoted()
        self.release = {'draft': False}
        self.assertIsNone(control.active_candidate())
        self.assertEqual(self.candidate, control.active_candidate(released=True))

    def test_doubt_keeps_the_candidate_active(self):
        self.promoted()
        for release, error, main in (({'draft': True}, None, None), (None, None, None),
                                     ({'draft': False}, True, None), ({'draft': False}, None, self.base)):
            self.release, self.issue_error = release, error
            self.remote['main'] = main or self.real('rev-parse', 'HEAD')
            self.assertEqual(self.candidate, control.active_candidate(), (release, error, main))
        self.release, self.issue_error, self.remote['main'] = {'draft': False}, None, self.real('rev-parse', 'HEAD')
        (self.root / '.github/release.json').write_text(self.real('show', f'{self.base}:.github/release.json'))
        self.assertEqual(self.candidate, control.active_candidate())

    def test_notify_closes_the_open_issue_and_leaves_the_candidate_file(self):
        head = self.promoted()
        self.release = {'draft': False}
        control.notify_release()
        self.assertEqual('closed', self.issue_state)
        self.assertIn('新版已发布', self.comments[-1]['body'])
        self.assertEqual([], self.pushed)
        self.assertEqual(head, self.remote['main'])
        self.assertTrue((self.root / '.automation/candidate.json').exists())
        self.assertTrue(any(c[1].endswith('/build/start') for c in self.calls))

    def test_every_reader_treats_a_finished_candidate_as_none(self):
        head = self.promoted()
        self.issue_state = 'closed'
        control.notify_release()
        self.assertEqual([], self.comments)
        self.assertFalse(any(c[0] == 'PATCH' for c in self.calls))
        self.assertIsNone(control.validate_source())
        self.commit('later.txt', 'x\n', 'unreviewed change')
        with self.assertRaisesRegex(ValueError, 'no approved candidate'):
            control.validate_source()
        self.remote['automation/upstream-v9.9.9'] = head
        with contextlib.redirect_stdout(io.StringIO()):
            control.resume_candidate(head, 'automation/upstream-v9.9.9', 217)
        self.assertFalse(any(c[1].endswith('/dispatches') for c in self.calls))

    def test_without_a_candidate_file_every_reader_sees_none(self):
        self.upstream()
        main = self.remote['main'] = self.base
        control.notify_release()
        self.assertEqual([], self.pushed)
        self.assertFalse(any('/issues/217' in c[1] for c in self.calls))
        self.assertIsNone(control.validate_source())
        self.remote['main'] = self.commit('later.txt', 'x\n', 'later')
        self.real('checkout', '-q', main)
        with self.assertRaisesRegex(ValueError, 'no approved candidate'):
            control.validate_source()
        self.remote['automation/upstream-v9.9.9'] = main
        with contextlib.redirect_stdout(io.StringIO()):
            control.resume_candidate(main, 'automation/upstream-v9.9.9', 217)
        self.assertFalse(any(c[1].endswith(('/dispatches', '/comments', '/pulls')) for c in self.calls))


if __name__ == '__main__':
    unittest.main()
