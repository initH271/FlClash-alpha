import json
import os
import unittest
from unittest.mock import patch

import security_scan as scan
import security_watch as watch
from security_groups import payload_for


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
        rows = watch.scan_history([finding], [], [finding])
        self.assertEqual('待核实（无索引替换）', rows[0]['state'])
        self.assertTrue(watch.unresolved_group({'history': rows, 'component_keys': [scan.key(finding)]},
                                              {'unscanned': [finding]}))

    def test_concatenated_go_module_json_is_parsed(self):
        self.assertEqual([{'Path': 'a'}, {'Path': 'b'}], list(scan.json_stream(' {"Path":"a"}\n {"Path":"b"}\n')))

    def test_group_record_is_signed_and_distinct_from_legacy_marker(self):
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            payload = payload_for('go-core')
            issue = {'author': {'username': 'Aharon', 'is_npc': False},
                     'body': '<!-- flclash-security-group ' + json.dumps(watch.sign(payload)) + ' -->'}
            self.assertEqual(payload, watch.record(issue))
            issue['body'] = issue['body'].replace('go-core', 'rust-api')
            self.assertIsNone(watch.record(issue))

    def test_snapshot_preserves_notes_and_encodes_comment_delimiters(self):
        with patch.dict(os.environ, {'UPSTREAM_APPROVAL_KEY': 'test-key'}):
            payload = payload_for('go-core')
            payload['package'] = 'literal --> delimiter'
            body = watch.snapshot_body({'body': 'Human assessment notes'}, payload, {'sha': 'a' * 40})
            issue = {'body': body, 'author': {'username': 'Aharon', 'is_npc': False}}
            self.assertEqual(payload, watch.record(issue))
            self.assertIn('Human assessment notes', body)
            self.assertEqual(body, watch.snapshot_body(issue, payload, {'sha': 'a' * 40}))

    def test_repair_group_requires_clean_indexed_dependency(self):
        item = self.finding()
        prefix = scan.key(item)[:12]
        with self.assertRaises(ValueError):
            scan.require_clean_group({'findings': [item], 'unscanned': []}, prefix)
        with self.assertRaises(ValueError):
            scan.require_clean_group({'findings': [], 'unscanned': [item]}, prefix)
        scan.require_clean_group({'findings': [], 'unscanned': []}, prefix)

    def test_related_packages_share_task_but_not_vulnerability_identity(self):
        a = self.finding()
        b = dict(a, name='another/module')
        helper = dict(a, name='tokio', ecosystem='crates.io', file='services/helper/Cargo.lock')
        rust_api = dict(helper, file='plugins/rust_api/rust/Cargo.lock')
        grouped = watch.groups({'findings': [a, b, helper, rust_api]})
        self.assertEqual({'go-core', 'rust-helper', 'rust-api'}, set(grouped))
        self.assertEqual(2, len(grouped['go-core']))

    def test_partial_group_repair_must_improve_without_new_risks(self):
        a = self.finding()
        b = self.finding('GO-2', ['CVE-2026-2222'])
        base = {'findings': [a, b], 'packages': [a], 'unscanned': []}
        scan.require_group_progress(base, {'findings': [b], 'unscanned': []}, 'go-core')
        for head in (base, {'findings': [self.finding('GO-3', ['CVE-2026-3333'])], 'unscanned': []},
                     {'findings': [], 'unscanned': [a]}):
            with self.assertRaises(ValueError):
                scan.require_group_progress(base, head, 'go-core')

    def test_migration_closes_records_as_consolidated_not_fixed(self):
        item = self.finding()
        with patch.object(watch, 'comment') as comment, patch.object(watch, 'api') as api:
            watch.migrate_legacy([({'number': '11', 'state': 'open'}, item)], {'go-core': '26'})
            self.assertIn('不表示漏洞已修复', comment.call_args.args[1])
            self.assertEqual('not_planned', api.call_args.args[2]['state_reason'])

    def test_running_group_worker_prevents_another_dispatch(self):
        state = {'npc': [{'context': {'npc.slug': '507space/FlClash-alpha', 'npc.name': '开发助手'},
                          'statuses': [{'state': 'pending'}]}]}
        self.assertTrue(watch.active_developer({'statuses': state}, []))
        state['npc'][0]['statuses'][0]['state'] = 'success'
        self.assertFalse(watch.active_developer({'statuses': state}, []))
