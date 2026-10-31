import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import control

ROOT = pathlib.Path(__file__).resolve().parents[1]
OWNER = {'login': control.OWNER, 'type': 'User'}
BOT = {'login': control.BOT, 'type': 'Bot'}
TAG = 'v9.9.9'
BRANCH = 'agent/upstream-' + TAG
GH_PR = 'https://github.com/example/pull/5'


def owner_says(body):
    return {'user': OWNER, 'author_association': 'OWNER', 'body': body}


class ApprovalRuleTests(unittest.TestCase):
    def test_only_the_exact_text_from_the_owner_approves(self):
        self.assertTrue(control.approved(owner_says(' OK '), TAG))
        self.assertTrue(control.approved(owner_says('ok ' + TAG), TAG))
        for body in ('looks OK', 'OK v9.9.8', 'OK\nrun anything', '', None):
            self.assertFalse(control.approved(owner_says(body), TAG), body)

    def test_login_type_and_association_must_all_match(self):
        for comment in ({'user': {'login': 'visitor', 'type': 'User'}, 'author_association': 'NONE', 'body': 'OK'},
                        {'user': {'login': control.OWNER.upper(), 'type': 'User'}, 'author_association': 'OWNER', 'body': 'OK'},
                        {'user': {'login': 'visitor', 'type': 'User'}, 'author_association': 'OWNER', 'body': 'OK'},
                        {'user': OWNER, 'author_association': 'COLLABORATOR', 'body': 'OK'},
                        {'user': OWNER, 'body': 'OK'},
                        {'user': {'login': control.OWNER, 'type': 'Bot'}, 'author_association': 'OWNER', 'body': 'OK'},
                        {'user': BOT, 'author_association': 'NONE', 'body': 'OK'},
                        {'body': 'OK'}):
            self.assertFalse(control.approved(comment, TAG), comment)

    def request(self, **change):
        issue = {'user': BOT, 'title': control.upstream_title(TAG),
                 'body': 'text\n\n' + control.marker({'tag': TAG, 'sha': 'a' * 40, 'upstream': control.POLICY['upstream']})}
        return control.upstream_request({**issue, **change})

    def test_only_an_issue_the_bot_opened_with_its_marker_counts(self):
        self.assertEqual(TAG, self.request()['tag'])
        self.assertIsNone(self.request(user={'login': 'visitor', 'type': 'User'}))
        self.assertIsNone(self.request(user=None))
        self.assertIsNone(self.request(pull_request={'url': 'x'}))
        self.assertIsNone(self.request(title='[上游升级] FlClash v1.0.0'))
        self.assertIsNone(self.request(body='nothing here'))
        self.assertIsNone(self.request(body=None))

    def test_the_marker_must_be_well_formed_and_name_the_upstream_we_follow(self):
        for payload in ('{not json}', '{"tag": "v9.9.9"}', '{"tag": 1, "sha": "a", "upstream": "b"}', '[1]'):
            self.assertIsNone(control.parse_request(f'<!-- flclash-upstream {payload} -->'), payload)
        other = control.marker({'tag': TAG, 'sha': 'a' * 40, 'upstream': 'attacker/FlClash'})
        self.assertIsNone(self.request(body=other))

    def test_quoted_text_cannot_stand_in_for_the_marker(self):
        planted = '> ' + control.marker({'tag': TAG, 'sha': 'b' * 40, 'upstream': control.POLICY['upstream']})
        self.assertIsNone(control.parse_request(planted))


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.posts, self.tracked = [], []
        self.release = {'tag_name': TAG, 'draft': False, 'prerelease': False,
                        'body': 'thanks @someone, see #12 and https://github.com/x/y/issues/3 ' + '<!-- flclash-upstream {} -->'}
        self.dispatch_error = None

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        if url.endswith('/releases/latest'):
            return self.release
        if '/git/ref/tags/' in url:
            return {'object': {'type': 'commit', 'sha': 'c' * 40}}
        if method == 'POST':
            self.posts.append((url, data))
            if url.endswith('/dispatches') and self.dispatch_error:
                raise self.dispatch_error
            return {'number': 40}
        self.fail(f'Unexpected API call: {method} {url}')

    def run_watch(self):
        with patch.object(control, 'api', self.api), patch.object(control, 'bot_issues', lambda state: iter(self.tracked)), \
                contextlib.redirect_stdout(io.StringIO()):
            control.watch()

    def test_a_new_version_opens_one_github_issue_for_the_owner_and_asks_for_analysis(self):
        self.run_watch()
        self.assertEqual(f'{control.GH}/issues', self.posts[0][0])
        issue = self.posts[0][1]
        self.assertEqual(control.upstream_title(TAG), issue['title'])
        self.assertEqual([control.OWNER], issue['assignees'])
        request = control.upstream_request({'user': BOT, 'title': issue['title'], 'body': issue['body']})
        self.assertEqual({'tag': TAG, 'sha': 'c' * 40, 'upstream': control.POLICY['upstream']}, request)
        url, data = self.posts[1]
        self.assertTrue(url.endswith('/actions/workflows/npc-upstream.yml/dispatches'))
        self.assertEqual({'ref': 'main', 'inputs': {'issue': '40', 'tag': TAG, 'base': control.POLICY['upstream_sha'],
                                                    'head': 'c' * 40}}, data)

    def test_the_body_mentions_nobody_and_carries_no_upstream_text(self):
        self.run_watch()
        body = self.posts[0][1]['body']
        for text in ('@', '#12', 'issues/3', 'thanks'):
            self.assertNotIn(text, body)
        self.assertEqual(1, body.count('flclash-upstream'))

    def test_one_version_opens_one_issue(self):
        self.tracked = [{'title': control.upstream_title(TAG), 'number': 3}]
        self.run_watch()
        self.assertEqual([], self.posts)

    def test_a_failed_analysis_request_keeps_the_issue(self):
        self.dispatch_error = control.HttpStatusError('POST api.github.com returned HTTP 500: ', 500)
        self.run_watch()
        self.assertEqual(2, len(self.posts))

    def test_old_prereleased_or_odd_versions_open_nothing(self):
        for change in ({'tag_name': control.POLICY['upstream_tag']}, {'prerelease': True}, {'draft': True}, {'tag_name': 'v9.9.9-pre.1'}):
            self.release.update(change)
            self.run_watch()
            self.assertEqual([], self.posts, change)
            self.release.update({'tag_name': TAG, 'draft': False, 'prerelease': False})


class UpgradeRepo(unittest.TestCase):
    """A real local repository; only git transport and the HTTP APIs are replaced."""

    def setUp(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        self.root = pathlib.Path(directory)
        for item in (patch.object(control, 'ROOT', self.root), patch.object(control, 'git', self.git),
                     patch.object(control, 'api', self.api), patch.object(control, 'pages', self.pages),
                     patch.dict(os.environ, {'ISSUE_NUMBER': ''})):
            item.start()
            self.addCleanup(item.stop)
        self.remote, self.pushed, self.calls = {}, [], []
        self.comments = [owner_says('OK')]
        self.pulls, self.issue_state, self.tag_sha = [], 'open', None
        self.real('init', '-q', '-b', 'main')
        self.real('config', 'user.name', 'Test')
        self.real('config', 'user.email', 'test@example.invalid')
        for name in ('.github/release.json', '.automation/policy.json'):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
            self.real('add', name)
        self.base = self.commit('app.txt', 'base\n', 'base')

    def real(self, *args, check=True, env=None):
        result = subprocess.run(['git', *args], cwd=self.root, env=env, text=True, capture_output=True, check=False)
        if check and result.returncode:
            raise RuntimeError(f'git {args[0]} failed: {result.stderr[-1500:]}')
        return result.stdout.strip() if check else result

    def git(self, *args, check=True, env=None):
        if args[0] == 'fetch':
            if args[1] == 'origin':
                self.real('update-ref', 'refs/remotes/origin/' + args[2], self.remote[args[2]])
            return '' if check else subprocess.CompletedProcess(args, 0, '', '')
        if args[0] == 'push':
            self.pushed.append((args[1], args[-1]))
            self.remote[args[-1]] = self.real('rev-parse', args[-1])
            return '' if check else subprocess.CompletedProcess(args, 0, '', '')
        return self.real(*args, check=check, env=env)

    def issue(self):
        return {'number': 217, 'state': self.issue_state, 'user': BOT, 'title': control.upstream_title(TAG),
                'body': control.marker(self.request)}

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        self.calls.append((method, url, data))
        if url.endswith('/comments') and method == 'POST':
            self.comments.append({'user': BOT, 'body': data['body']})
            return {}
        if url.endswith(f'/git/ref/heads/{BRANCH}'):
            return {'object': {'sha': self.remote[BRANCH]}} if BRANCH in self.remote else None
        if '/pulls?state=all&head=' in url:
            return self.pulls
        if url.endswith('/pulls') and method == 'POST':
            self.pulls.append({'number': 5})
            return {'number': 5, 'html_url': GH_PR}
        if '/git/ref/tags/' in url:
            return {'object': {'type': 'commit', 'sha': self.tag_sha or self.request['sha']}}
        if url.endswith('/issues/217'):
            return self.issue()
        self.fail(f'Unexpected API call: {method} {url}')

    def pages(self, url, page_key='page', size_key='per_page'):
        if url.endswith('/issues/217/comments'):
            return list(self.comments)
        if '/issues?state=open' in url:
            return [self.issue()]
        self.fail('Unexpected listing: ' + url)

    def commit(self, name, text, message):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.real('add', name)
        self.real('commit', '-q', '-m', message)
        return self.real('rev-parse', 'HEAD')

    def upstream(self, protected=False, app='upstream\n'):
        """An upstream release commit built on the shared base."""
        self.real('checkout', '-q', '-b', 'upstream', self.base)
        sha = self.base
        if protected:
            sha = self.commit('.github/upstream.yml', 'ci\n', 'upstream ci')
        if app:
            sha = self.commit('app.txt', app, 'upstream app')
        self.request = {'tag': TAG, 'sha': sha, 'upstream': control.POLICY['upstream']}
        self.real('checkout', '-q', 'main')
        return sha

    def posted(self):
        return [c for c in self.calls if c[0] != 'GET']

    def bot_comments(self):
        return [c['body'] for c in self.comments if c['user'] == BOT]


class CleanUpgradeTests(UpgradeRepo):
    def setUp(self):
        super().setUp()
        self.upstream_sha = self.upstream()
        self.remote['main'] = self.commit('personal.txt', 'mine\n', 'personal change')

    def test_an_ok_opens_one_ordinary_pr_that_changes_only_what_it_should(self):
        control.approvals()
        head = self.remote[BRANCH]
        parents = self.real('rev-list', '--parents', '-n1', head).split()[1:]
        self.assertEqual([self.remote['main'], self.upstream_sha], parents)
        changed = self.real('diff', '--name-only', self.remote['main'], head).splitlines()
        self.assertEqual(['.automation/policy.json', 'app.txt'], changed)
        policy = json.loads(self.real('show', f'{head}:.automation/policy.json'))
        self.assertEqual((TAG, self.upstream_sha), (policy['upstream_tag'], policy['upstream_sha']))
        self.assertEqual(self.real('show', f'{self.base}:.github/release.json'), self.real('show', f'{head}:.github/release.json'))
        pr = [c for c in self.calls if c[1].endswith('/pulls')][0][2]
        self.assertEqual((BRANCH, 'main'), (pr['head'], pr['base']))
        self.assertNotIn('draft', pr)
        self.assertIn('Closes #217', pr['body'])
        self.assertIn('Approve workflows to run', pr['body'])
        self.assertEqual([('origin', BRANCH)], self.pushed)
        comment = self.bot_comments()[-1]
        self.assertIn(GH_PR, comment)
        self.assertIn('Approve workflows to run', comment)
        self.assertNotIn('@', comment)

    def test_no_workflow_is_dispatched_since_its_checks_would_not_count(self):
        control.approvals()
        self.assertFalse(any('dispatches' in c[1] for c in self.calls))

    def test_the_next_pass_changes_nothing(self):
        control.approvals()
        posted, pushed = len(self.posted()), list(self.pushed)
        control.approvals()
        self.assertEqual(posted, len(self.posted()))
        self.assertEqual(pushed, self.pushed)

    def test_a_pr_the_owner_closed_is_not_reopened(self):
        control.approvals()
        self.pulls[0]['state'] = 'closed'
        posted = len(self.posted())
        control.approvals()
        self.assertEqual(posted, len(self.posted()))

    def test_a_branch_pushed_before_a_crash_still_gets_its_pr(self):
        self.remote[BRANCH] = self.remote['main']
        control.approvals()
        self.assertEqual([{'number': 5}], self.pulls)
        self.assertEqual([], self.pushed)

    def test_the_owner_merging_upstream_by_hand_still_records_the_version(self):
        self.real('checkout', '-q', 'main')
        self.real('merge', '-q', '--no-ff', '-X', 'theirs', '-m', 'owner merges upstream', self.upstream_sha)
        main = self.remote['main'] = self.real('rev-parse', 'HEAD')
        control.approvals()
        self.assertEqual([main], self.real('rev-list', '--parents', '-n1', self.remote[BRANCH]).split()[1:])
        self.assertEqual(['.automation/policy.json'], self.real('diff', '--name-only', main, self.remote[BRANCH]).splitlines())

    def test_nothing_happens_without_an_owner_ok(self):
        for comments in ([], [{'user': {'login': 'visitor', 'type': 'User'}, 'author_association': 'NONE', 'body': 'OK'}],
                         [owner_says('OK later')]):
            self.comments = comments
            control.approvals()
            self.assertEqual([], self.posted(), comments)
            self.assertEqual([], self.pushed)

    def test_a_comment_on_someone_elses_issue_does_nothing(self):
        issue = dict(self.issue(), user={'login': 'visitor', 'type': 'User'})
        with patch.object(self, 'issue', return_value=issue), patch.dict(os.environ, {'ISSUE_NUMBER': '217'}):
            control.approvals()
        self.assertEqual([], self.posted())

    def test_a_comment_triggered_run_reads_only_that_issue(self):
        with patch.dict(os.environ, {'ISSUE_NUMBER': '217'}):
            control.approvals()
        self.assertIn(('GET', f'{control.GH}/issues/217', None), self.calls)
        self.assertEqual({'number': 5}, self.pulls[0])

    def test_a_closed_issue_withdraws_the_upgrade(self):
        self.issue_state = 'closed'
        with patch.dict(os.environ, {'ISSUE_NUMBER': '217'}):
            control.approvals()
        self.assertEqual([], self.posted())

    def test_a_version_main_already_follows_is_ignored(self):
        self.request['tag'] = control.POLICY['upstream_tag']
        with patch.object(self, 'issue', return_value=dict(self.issue(), title=control.upstream_title(self.request['tag']))):
            control.approvals()
        self.assertEqual([], self.posted())

    def test_a_moved_tag_stops_and_reports_once(self):
        self.tag_sha = 'f' * 40
        for _ in range(2):
            control.approvals()
        self.assertEqual([], self.pushed)
        self.assertEqual(1, len(self.bot_comments()))
        self.assertIn('标签指向已变化', self.bot_comments()[0])

    def test_a_pasted_stamp_does_not_silence_the_report(self):
        self.tag_sha = 'f' * 40
        self.comments.append(owner_says(f'<!-- flclash-tag-moved {self.request["sha"]} -->'))
        control.approvals()
        self.assertEqual(1, len(self.bot_comments()))


class ConflictTests(UpgradeRepo):
    def test_a_conflict_reports_once_and_pushes_nothing(self):
        upstream = self.upstream(protected=True)
        self.remote['main'] = self.commit('app.txt', 'personal\n', 'personal change')
        for _ in range(2):
            control.approvals()
        self.assertEqual(self.remote.get(BRANCH), None)
        self.assertEqual([], self.pushed)
        self.assertEqual([], [c for c in self.calls if c[1].endswith('/pulls') and c[0] == 'POST'])
        self.assertEqual(1, len(self.bot_comments()))
        body = self.bot_comments()[0]
        for text in ('1 个冲突文件和 1 个受保护文件', '- `app.txt`', '- `.github/upstream.yml`', upstream,
                     'Closes #217', 'AUTOMATION.md 的 Conflicting upstream upgrades 一节'):
            self.assertIn(text, body)
        self.assertNotIn('@', body)
        self.assertEqual(self.remote['main'], self.real('rev-parse', 'origin/main'))
        self.assertIn('### Conflicting upstream upgrades\n', (ROOT / 'AUTOMATION.md').read_text())

    def test_a_clean_change_to_a_protected_path_is_also_handed_over(self):
        self.upstream(protected=True, app=None)
        self.remote['main'] = self.commit('personal.txt', 'mine\n', 'personal change')
        control.approvals()
        self.assertEqual([], self.pushed)
        self.assertIn('0 个冲突文件和 1 个受保护文件', self.bot_comments()[0])

    def test_the_listing_is_capped(self):
        self.assertIn('另有 2 个未列出', control.listed([f'f{i}' for i in range(12)]))
        self.assertNotIn('f10', control.listed([f'f{i}' for i in range(12)]))


class ReleaseNotifyTests(unittest.TestCase):
    """notify_release sits on the release path: whatever happens to the Issues, the mirror must hear of the release."""

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        self.calls.append((method, url, data))
        if url.endswith('/build/start'):
            return None
        if '/actions/runs/' in url:
            return {'display_title': 'Android ' + 'a' * 40}
        return {}

    def setUp(self):
        self.calls = []
        for item in (patch.object(control, 'api', self.api),
                     patch.object(control, 'git', return_value=subprocess.CompletedProcess([], 0, '', ''))):
            item.start()
            self.addCleanup(item.stop)

    def assert_mirror_started(self):
        self.assertEqual(('POST', f'{control.CNB}/build/start'), self.calls[-1][:2])
        self.assertEqual('api_trigger', self.calls[-1][2]['event'])
        self.assertEqual('main', self.calls[-1][2]['branch'])

    def notify(self, issues):
        with patch.object(control, 'bot_issues', lambda state: iter(issues)), contextlib.redirect_stdout(io.StringIO()):
            control.notify_release()

    def test_a_release_starts_the_mirror_without_any_key_or_candidate(self):
        with patch.dict(os.environ):
            os.environ.pop('UPSTREAM_APPROVAL_KEY', None)
            self.notify([])
        self.assert_mirror_started()
        self.assertFalse((ROOT / '.automation/candidate.json').exists())

    def test_a_github_failure_while_tidying_still_starts_the_mirror(self):
        for error in (control.HttpStatusError('GET api.github.com returned HTTP 403: ', 403), OSError('down'), KeyError('title')):
            self.calls.clear()
            with patch.object(control, 'close_published_failures', side_effect=error), contextlib.redirect_stdout(io.StringIO()):
                control.notify_release()
            self.assert_mirror_started()

    def test_a_mirror_that_cannot_start_fails_the_step(self):
        with patch.object(control, 'api', side_effect=control.HttpStatusError('POST api.cnb.cool returned HTTP 401: ', 401)), \
                patch.object(control, 'bot_issues', lambda state: iter([])):
            with self.assertRaises(control.HttpStatusError):
                control.notify_release()

    def test_a_published_successor_closes_the_old_failure_on_github(self):
        self.notify([{'number': 9, 'title': '[构建待处理] GitHub #77'}, {'number': 10, 'title': control.upstream_title(TAG)}])
        writes = [c for c in self.calls if c[0] != 'GET' and not c[1].endswith('/build/start')]
        self.assertEqual([('POST', f'{control.GH}/issues/9/comments'), ('PATCH', f'{control.GH}/issues/9')],
                         [c[:2] for c in writes])
        self.assertEqual('closed', writes[1][2]['state'])
        self.assert_mirror_started()


class IssueListingTests(unittest.TestCase):
    def test_only_real_issues_by_the_bot_are_listed(self):
        rows = [{'number': 1, 'user': BOT}, {'number': 2, 'user': BOT, 'pull_request': {}},
                {'number': 3, 'user': {'login': 'visitor'}}, {'number': 4, 'user': None}]
        with patch.object(control, 'pages', return_value=rows) as pages:
            self.assertEqual([1], [i['number'] for i in control.bot_issues('all')])
        self.assertIn(f'{control.GH}/issues?state=all', pages.call_args.args[0])
        self.assertIn('creator=github-actions%5Bbot%5D', pages.call_args.args[0])


class NoRecordKeysTests(unittest.TestCase):
    def test_nothing_signs_or_verifies_records_any_more(self):
        for name in ('sign', 'verify', 'active_candidate', 'prepare_candidate', 'source_tree', 'paired_review'):
            self.assertFalse(hasattr(control, name), name)
        for path in (ROOT / '.github/workflows').glob('*.y*ml'):
            self.assertNotIn('UPSTREAM_APPROVAL_KEY', path.read_text(encoding='utf-8'), path.name)
        self.assertNotIn('UPSTREAM_APPROVAL_KEY', re.sub(r'#.*', '', (ROOT / '.automation/control.py').read_text(encoding='utf-8')))
        self.assertNotIn('approver', control.POLICY)
