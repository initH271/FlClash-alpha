import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import control


class RefreshTests(unittest.TestCase):
    def test_refresh_requires_unchanged_source_and_current_approval(self):
        candidate = {'tree': 'signed-tree', 'base': 'old-main', 'upstream_sha': 'upstream'}
        request = {'sha': 'upstream', 'tag': 'v0.8.98', 'upstream': control.POLICY['upstream']}
        for tree, issue_state, approved, tag, allowed in (
                ('changed', 'open', True, 'upstream', False),
                ('signed-tree', 'closed', True, 'upstream', False),
                ('signed-tree', 'open', False, 'upstream', False),
                ('signed-tree', 'open', True, 'moved-tag', False),
                ('signed-tree', 'open', True, 'upstream', True)):
            def git(*args, **kwargs):
                if args[0] == 'rev-parse':
                    return 'new-main'
                return types.SimpleNamespace(returncode=0)
            with (self.subTest(tree=tree, state=issue_state, approval=approved, tag=tag),
                  patch.object(control, 'source_tree', return_value=tree),
                  patch.object(control, 'api', return_value={'state': issue_state, 'body': 'signed'}),
                  patch.object(control, 'parse_request', return_value=request),
                  patch.object(control, 'pages', return_value=[{}]),
                  patch.object(control, 'approved', return_value=approved),
                  patch.object(control, 'upstream_commit', return_value=tag),
                  patch.object(control, 'git', side_effect=git),
                  patch.object(control, 'prepare_candidate') as prepare):
                control.refresh_candidate(candidate, 'old-head', 'candidate', 1, 'new-main')
                self.assertEqual(prepare.called, allowed)
                if allowed:
                    prepare.assert_called_once_with(request, 1, 'candidate', previous='old-head')

    def test_refreshed_commit_preserves_main_tree_and_fast_forward_history(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(control, 'ROOT', pathlib.Path(directory)):
            root = pathlib.Path(directory)
            control.git('init', '-b', 'main')
            control.git('config', 'user.name', 'Test')
            control.git('config', 'user.email', 'test@example.invalid')
            (root / 'base.txt').write_text('base')
            control.git('add', '.')
            control.git('commit', '-m', 'base')
            control.git('checkout', '-b', 'candidate')
            (root / 'upstream.txt').write_text('approved upstream')
            control.git('add', '.')
            control.git('commit', '-m', 'old candidate')
            previous = control.git('rev-parse', 'HEAD')
            control.git('checkout', 'main')
            (root / 'automation.txt').write_text('latest main automation')
            control.git('add', '.')
            control.git('commit', '-m', 'advance main')
            base = control.git('rev-parse', 'HEAD')
            control.git('checkout', '-B', 'candidate', base)
            (root / 'upstream.txt').write_text('approved upstream')
            control.git('add', '.')
            expected = control.git('write-tree')
            control.commit_candidate('candidate', base, previous)
            self.assertEqual(expected, control.git('rev-parse', 'HEAD^{tree}'))
            self.assertEqual(previous, control.git('rev-parse', 'HEAD^1'))
            self.assertEqual(base, control.git('rev-parse', 'HEAD^2'))
            self.assertEqual(0, control.git('merge-base', '--is-ancestor', previous, 'HEAD', check=False).returncode)
            self.assertEqual('latest main automation', (root / 'automation.txt').read_text())
