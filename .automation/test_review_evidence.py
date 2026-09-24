import types
import unittest
from unittest.mock import patch

import review_evidence as evidence


class ReviewEvidenceTests(unittest.TestCase):
    def test_reviewers_get_the_exact_fetch_command_for_the_pinned_commits(self):
        for platform, host in (('cnb', 'https://cnb.cool/'), ('github', 'https://github.com/')):
            request = {'platform': platform, 'base': 'a' * 40, 'head': 'b' * 40}
            with patch.object(evidence, 'evidence', return_value={}):
                text = evidence.describe(request)
            self.assertIn(f'git fetch --no-tags {host}', text)
            self.assertIn(f'{"a" * 40} {"b" * 40}`', text)
            self.assertIn(f'git show {"b" * 40}:', text)

    def test_manifest_uses_merge_base_diff_and_fixed_blobs(self):
        request = {'platform': 'cnb', 'base': 'a' * 40, 'head': 'b' * 40}
        calls = []
        def git(*args, **kwargs):
            calls.append(args)
            if args[0] == 'fetch':
                return ''
            if args[0] == 'merge-base':
                return 'c' * 40
            if args[0] == 'diff':
                self.assertEqual('a' * 40 + '...' + 'b' * 40, args[-1])
                return 'core/go.mod\0'
            if args[0] == 'rev-parse':
                return types.SimpleNamespace(returncode=0, stdout=args[-1].split(':')[0])
            return types.SimpleNamespace(returncode=0, stdout='d' * 40 + '\n')
        with patch.object(evidence, 'git', side_effect=git):
            result = evidence.evidence(request)
        self.assertEqual('c' * 40, result['files'][0]['ancestor_blob'])
        self.assertEqual('b' * 40, result['files'][0]['head_blob'])
        self.assertEqual('d' * 40, result['merged_tree'])

    def test_unpinned_reference_is_rejected_before_fetch(self):
        with patch.object(evidence, 'git') as git, self.assertRaises(ValueError):
            evidence.evidence({'platform': 'cnb', 'base': 'main', 'head': 'b' * 40})
        git.assert_not_called()

    def test_content_conflict_is_distinct_from_fatal_git_failure(self):
        request = {'platform': 'cnb', 'base': 'a' * 40, 'head': 'b' * 40}
        for code in (1, 128):
            with patch.object(evidence, 'git', side_effect=['', 'c' * 40, '',
                    types.SimpleNamespace(returncode=code, stdout='d' * 40 + '\n')]):
                if code == 1:
                    result = evidence.evidence(request)
                    self.assertTrue(result['merge_conflict'])
                    self.assertIsNone(result['merged_tree'])
                else:
                    with self.assertRaises(RuntimeError):
                        evidence.evidence(request)
