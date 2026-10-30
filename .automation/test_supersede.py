import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import control

OWNER = {'username': 'Aharon', 'is_npc': False}
RELEASE = {'tag_name': 'v9.0.0', 'draft': False, 'prerelease': False, 'html_url': 'u', 'body': ''}


class Fake:
    """Stands in for control.api and control.pages with their real signatures."""

    def __init__(self, issues, comments=None, branches=(), branch_error=None, states=None, fail=()):
        self.issues = issues
        self.comments = comments or {}
        self.branches = set(branches)
        self.branch_error = branch_error
        self.states = states or {}
        self.fail = fail  # methods whose write raises (POST: comments only)
        self.writes = []

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        if url.endswith('/releases/latest'):
            return RELEASE
        if '/git/ref/tags/' in url:
            return {'object': {'type': 'commit', 'sha': 'a' * 40}}
        if '/git/ref/heads/' in url:
            if self.branch_error:
                raise self.branch_error
            return {'object': {'sha': 'b' * 40}} if url.rsplit('/heads/', 1)[1] in self.branches else None
        if method == 'GET' and '/issues/' in url and url.rsplit('/', 1)[1] in self.states:
            return {'state': self.states[url.rsplit('/', 1)[1]], 'body': ''}
        if method in self.fail and (method != 'POST' or url.endswith('/comments')):
            raise RuntimeError(f'{method} failed')
        self.writes.append((method, url, data))
        return {'number': 900} if url.endswith('/issues') and method == 'POST' else None

    def pages(self, url, page_key='page', size_key='page_size'):
        return iter(self.comments.get(url.split('/issues/')[1].split('/')[0], []) if '/comments' in url
                    else self.issues)

    def closed(self):
        return [w[1].rsplit('/', 1)[1] for w in self.writes if w[0] == 'PATCH']

    def comment_texts(self):
        return [w[2]['body'] for w in self.writes if w[1].endswith('/comments')]


def old(number, tag):
    return {'number': number, 'title': f'[上游升级] FlClash {tag}'}


class SupersedeTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'unit-test-key'})
        env.start()
        self.addCleanup(env.stop)
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        (pathlib.Path(self.root.name) / '.automation').mkdir()

    def run_watch(self, fake):
        with patch.object(control, 'api', fake.api), patch.object(control, 'pages', fake.pages), \
                patch.object(control, 'ROOT', pathlib.Path(self.root.name)), \
                patch.dict(control.POLICY, {'upstream_tag': 'v0.0.1'}):
            control.watch()

    def candidate(self, issue):
        envelope = control.sign({'issue': str(issue)})
        (pathlib.Path(self.root.name) / '.automation/candidate.json').write_text(json.dumps(envelope))

    def test_idle_older_issue_commented_and_closed(self):
        fake = Fake([old(5, 'v1.0.0')])
        self.run_watch(fake)
        self.assertEqual(['5'], fake.closed())
        self.assertEqual(['已被 v9.0.0 取代（#900）。'], fake.comment_texts())
        patch_data = [w[2] for w in fake.writes if w[0] == 'PATCH'][0]
        self.assertEqual({'state': 'closed', 'state_reason': 'not_planned'}, patch_data)

    def test_valid_owner_ok_keeps_issue(self):
        # approved() matches 'ok' / 'ok <tag>' case-insensitively; the plain 'OK' here is just one spelling.
        fake = Fake([old(5, 'v1.0.0')], {'5': [{'author': OWNER, 'body': 'OK'}]})
        self.run_watch(fake)
        self.assertEqual([], fake.closed())

    def test_upstream_branch_keeps_issue(self):
        fake = Fake([old(5, 'v1.0.0')], branches={'automation/upstream-v1.0.0'})
        self.run_watch(fake)
        self.assertEqual([], fake.closed())

    def test_candidate_pointing_at_issue_keeps_it(self):
        self.candidate(5)
        fake = Fake([old(5, 'v1.0.0')])
        self.run_watch(fake)
        self.assertEqual([], fake.closed())

    def test_finished_candidate_does_not_keep_its_issue(self):
        # active_candidate() returns None once the upgrade issue is closed.
        self.candidate(5)
        fake = Fake([old(5, 'v1.0.0')], states={'5': 'closed'})
        self.run_watch(fake)
        self.assertEqual(['5'], fake.closed())

    def test_candidate_for_another_issue_does_not_protect_this_one(self):
        self.candidate(7)
        fake = Fake([old(5, 'v1.0.0')])
        self.run_watch(fake)
        self.assertEqual(['5'], fake.closed())

    def test_candidate_for_another_issue_still_honours_owner_ok(self):
        self.candidate(7)
        fake = Fake([old(5, 'v1.0.0')], {'5': [{'author': OWNER, 'body': 'ok v1.0.0'}]})
        self.run_watch(fake)
        self.assertEqual([], fake.closed())

    def test_candidate_for_another_issue_still_honours_upstream_branch(self):
        self.candidate(7)
        fake = Fake([old(5, 'v1.0.0')], branches={'automation/upstream-v1.0.0'})
        self.run_watch(fake)
        self.assertEqual([], fake.closed())

    def test_failed_close_posts_no_superseded_comment(self):
        fake = Fake([old(5, 'v1.0.0')], fail=('PATCH',))
        self.run_watch(fake)
        self.assertEqual([], fake.closed())
        self.assertEqual([], fake.comment_texts())

    def test_failed_comment_after_close_leaves_it_closed_and_logged(self):
        fake = Fake([old(5, 'v1.0.0')], fail=('POST',))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.run_watch(fake)
        self.assertEqual(['5'], fake.closed())
        self.assertIn('is closed but the comment failed', out.getvalue())

    def test_higher_version_untouched(self):
        fake = Fake([old(5, 'v9.0.1'), old(6, 'v10.0.0')])
        self.run_watch(fake)
        self.assertEqual([], fake.closed())

    def test_branch_lookup_error_keeps_issue(self):
        fake = Fake([old(5, 'v1.0.0')], branch_error=control.HttpStatusError('boom', 500))
        self.run_watch(fake)
        self.assertEqual([], fake.closed())

    def test_no_new_issue_means_no_cleanup(self):
        fake = Fake([old(5, 'v1.0.0'), old(7, 'v9.0.0')])
        self.run_watch(fake)
        self.assertEqual([], fake.closed())
        self.assertEqual([], fake.writes)


if __name__ == '__main__':
    unittest.main()
