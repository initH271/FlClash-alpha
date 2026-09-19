import json
import os
import unittest
from unittest.mock import patch

import security_scan as scan
import security_watch as watch


class SecurityTests(unittest.TestCase):
    def finding(self, identifier='GO-1', aliases=None, version='v1.0.0'):
        return {'file': 'core/go.mod', 'ecosystem': 'Go', 'name': 'example.org/module',
                'version': version, 'id': identifier, 'aliases': aliases or ['CVE-2026-1234', identifier],
                'fixed': ['v1.0.1'], 'url': 'https://osv.dev/vulnerability/GO-1'}

    def test_aliases_deduplicate_without_hiding_new_cves(self):
        old = {'findings': [self.finding()]}
        same = self.finding('GHSA-1', ['CVE-2026-1234', 'GHSA-1'], 'v1.0.1')
        new = self.finding('GO-2', ['CVE-2026-2222', 'GO-2'])
        self.assertEqual([new], scan.new_findings(old, {'findings': [same, new]}))
        grouped = watch.groups({'findings': [self.finding(), self.finding('GHSA-1', ['CVE-2026-1234', 'GHSA-1'])]})
        self.assertEqual(1, len(next(iter(grouped.values()))))

    def test_incomplete_and_stale_scans_cannot_close_issues(self):
        with patch.object(watch, 'api', return_value={'object': {'sha': 'new'}}) as api:
            with self.assertRaises(ValueError):
                watch.monitor({'schema': 1, 'complete': False})
            api.assert_not_called()
            with self.assertRaises(ValueError):
                watch.monitor({'schema': 1, 'complete': True, 'sha': 'old'})
            self.assertEqual(1, api.call_count)

    def test_local_replacement_cannot_automatically_close_security_issue(self):
        finding = self.finding()
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            payload = {'key': scan.key(finding)}
            issue = {'number': '9', 'state': 'open', 'author': {'username': 'Aharon', 'is_npc': False},
                     'body': '<!-- flclash-security ' + json.dumps(watch.sign(payload)) + ' -->'}
            def api(url, *args, **kwargs):
                return {'object': {'sha': 'current'}} if 'git/ref' in url else issue
            with (patch.object(watch, 'api', side_effect=api), patch.object(watch, 'cnb_risks', return_value={}),
                  patch.object(watch, 'all_issues', return_value=[issue]), patch.object(watch, 'comment') as comment):
                watch.monitor({'schema': 1, 'complete': True, 'sha': 'current', 'findings': [],
                               'packages': [], 'unscanned': [finding]})
                comment.assert_not_called()

    def test_concatenated_go_module_json_is_parsed(self):
        self.assertEqual([{'Path': 'a'}, {'Path': 'b'}], list(scan.json_stream(' {"Path":"a"}\n {"Path":"b"}\n')))

    def test_repair_group_requires_clean_indexed_dependency(self):
        item = self.finding()
        prefix = scan.key(item)[:12]
        with self.assertRaises(ValueError):
            scan.require_clean_group({'findings': [item], 'unscanned': []}, prefix)
        with self.assertRaises(ValueError):
            scan.require_clean_group({'findings': [], 'unscanned': [item]}, prefix)
        scan.require_clean_group({'findings': [], 'unscanned': []}, prefix)
