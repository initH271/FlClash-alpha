import os
import subprocess
import unittest
from unittest.mock import patch

import control
import requirements as req
from test_requirements import BODY

MAIN = 'a' * 40
HEAD = 'c' * 40
OLD = 'b' * 40
CNB_PULL = {'number': '5', 'state': 'open',
            'head': {'ref': 'refs/heads/automation/req-9', 'repo': {'path': control.POLICY['cnb']}}}
ALLOWED = BODY.replace('## 允许改自动化配置\n\n未勾选', '## 允许改自动化配置\n\n- [x] 允许改自动化配置')


class PathGuardTests(unittest.TestCase):
    """Drive the real forward/advance/reconcile; only the network layer is replaced."""

    def setUp(self):
        env = patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'})
        env.start()
        self.addCleanup(env.stop)
        self.posted = []
        self.files = []
        self.opened = False

    def api(self, url, method='GET', data=None, missing=False, timeout=60):
        if url.endswith('/git/ref/heads/main'):
            return {'object': {'sha': MAIN}}
        if '/pulls?state=open&head=' in url:
            return [{'number': 4, 'head': {'sha': OLD}, 'html_url': 'https://github.com/x/pull/4'}] if self.opened else []
        if '/pulls?state=closed&head=' in url:
            return []
        if '/git/ref/heads/automation/req-9' in url:
            return None
        if url.endswith('/pulls') and method == 'POST':
            return {'number': 7, 'html_url': 'https://github.com/x/pull/7'}
        if url.endswith('/issues/9'):
            return self.issue
        return {}

    def pages(self, url, page_key='page', size_key='page_size'):
        if '/issues/9/comments' in url:
            return [{'created_at': f'2026-09-22T02:0{i}:00Z', 'body': body} for i, body in enumerate(self.posted)]
        if '/pulls?state=open' in url:
            return [CNB_PULL]
        if '/issues?state=open' in url:
            return [self.issue]
        return []

    def comment(self, number, body, work_mode=False):
        self.posted.append(body)
        return {}

    def git(self, *args, check=True, env=None):
        out = {'diff': '\n'.join(self.files) + '\n', 'rev-parse': 't' * 40 + '\n'}.get(args[0], '')
        if check:
            return out.strip()
        return subprocess.CompletedProcess(['git', *args], 0, out, '')

    def run_with(self, call, body=BODY, files=(), opened=False):
        self.issue = {'number': '9', 'title': '[需求] 导出', 'state': 'open', 'body': body,
                      'author': {'username': control.POLICY['approver'], 'is_npc': False}}
        self.files, self.opened = list(files), opened
        with (patch.object(control, 'api', side_effect=self.api), patch.object(control, 'pages', side_effect=self.pages),
              patch.object(control, 'comment', side_effect=self.comment),
              patch.object(control, 'git', side_effect=self.git),
              patch.object(req, 'push_github') as push, patch.object(req, 'settle') as settle):
            call(self.issue)
        return push, settle

    def stops(self, guard):
        marks = req.markers([{'created_at': '', 'body': body} for body in self.posted])
        return [item for item in marks if item.get('guard') == guard and item.get('phase') == 'stuck'
                and item.get('head') == HEAD]

    def test_a_workflow_change_is_stopped_once_per_head_and_never_pushed(self):
        files = ['lib/main.dart', '.github/workflows/build.yaml']
        for body in (BODY, ALLOWED):
            self.posted = []
            for _ in range(2):
                push, settle = self.run_with(lambda issue: req.forward(issue, '9', HEAD), body, files)
                push.assert_not_called()
                settle.assert_not_called()
            self.assertEqual(1, len(self.posted), self.posted)
            self.assertEqual(1, len(self.stops('workflows')))
            self.assertIn('owner 通道', self.posted[0])
            self.assertIn('.github/workflows/build.yaml', self.posted[0])
            self.assertEqual('stuck', req.markers([{'created_at': '', 'body': self.posted[0]}])[0]['phase'])

    def test_a_workflow_change_stops_the_fast_forward_of_an_open_pull(self):
        for _ in range(2):
            push, settle = self.run_with(lambda issue: req.forward(issue, '9', HEAD),
                                         files=['.github/workflows/build.yaml'], opened=True)
            push.assert_not_called()
            settle.assert_not_called()
        self.assertEqual(1, len(self.stops('workflows')))

    def test_an_unauthorized_protected_change_is_refused_and_listed(self):
        for opened in (False, True):
            self.posted = []
            push, settle = self.run_with(lambda issue: req.forward(issue, '9', HEAD),
                                         files=['.cnb.yml', '.automation/x.py', 'lib/a.dart', '.cnbx'], opened=opened)
            push.assert_not_called()
            settle.assert_not_called()
            self.assertEqual(1, len(self.stops('protected')), self.posted)
            self.assertIn('`.cnb.yml`', self.posted[0])
            self.assertIn('`.automation/x.py`', self.posted[0])
            self.assertNotIn('lib/a.dart', self.posted[0])
            self.assertNotIn('.cnbx', self.posted[0])

    def test_an_authorized_protected_change_forwards_as_before(self):
        for opened in (False, True):
            push, settle = self.run_with(lambda issue: req.forward(issue, '9', HEAD), ALLOWED,
                                         files=['.cnb.yml', '.automation/x.py'], opened=opened)
            push.assert_called_once_with(HEAD, 'automation/req-9')
            settle.assert_called_once()
            self.assertFalse(self.stops('protected'))

    def test_a_change_outside_protected_paths_forwards_as_before(self):
        for opened in (False, True):
            self.posted = []
            push, settle = self.run_with(lambda issue: req.forward(issue, '9', HEAD),
                                         files=['lib/a.dart', 'docs/.github/workflows/x'], opened=opened)
            push.assert_called_once_with(HEAD, 'automation/req-9')
            settle.assert_called_once()
            self.assertEqual(1, len(self.posted))
            self.assertIn('GitHub', self.posted[0])

    def reconcile(self, files):
        dispatch = {'kind': 'dispatch', 'phase': 'dev', 'rung': 60, 'tree': 't' * 40, 'role': '开发助手',
                    'work_mode': True, 'instruction': '改'}
        with (patch.object(req, 'branch_sha', return_value=HEAD),
              patch.object(req, 'check_state', return_value=(False, False)),
              patch.object(req, 'contained', return_value=False),
              patch.object(req, 'foreign_commits', return_value=[]),
              patch.object(req, 'decide', return_value=dispatch)):
            self.run_with(lambda issue: req.reconcile(), files=files)

    def test_a_workflow_change_is_not_dispatched_again(self):
        self.reconcile(['.github/workflows/build.yaml'])
        self.reconcile(['.github/workflows/build.yaml'])
        self.assertEqual(1, len(self.posted), self.posted)
        self.assertEqual(1, len(self.stops('workflows')))

    def test_dispatch_is_unchanged_without_a_workflow_change(self):
        self.reconcile(['.cnb.yml'])
        self.assertEqual(1, len(self.posted))
        self.assertIn('@' + control.POLICY['cnb'] + '(开发助手)', self.posted[0])


if __name__ == '__main__':
    unittest.main()
