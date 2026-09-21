import json
import os
import ssl
import unittest
import urllib.error
from unittest.mock import Mock, patch

import security_scan as scan
import security_watch as watch
from security_groups import payload_for


class SecurityTests(unittest.TestCase):
    def test_osv_tls_eof_retries_read_query_without_changing_payload(self):
        payload = {'queries': []}
        failure = urllib.error.URLError(ssl.SSLEOFError('connection closed'))
        with patch.object(scan, 'api', side_effect=[failure, {'results': []}]) as api, patch.object(scan.time, 'sleep'):
            self.assertEqual({'results': []}, scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', payload))
            self.assertEqual(2, api.call_count)
            self.assertEqual(api.call_args_list[0], api.call_args_list[1])

    def test_osv_exhausted_network_retries_fail_instead_of_reporting_clean(self):
        with patch.object(scan, 'api', side_effect=TimeoutError) as api, patch.object(scan.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', {})
            self.assertEqual(3, api.call_count)

    def test_osv_certificate_and_application_errors_are_not_retried(self):
        for error in (urllib.error.URLError(ssl.SSLCertVerificationError('invalid certificate')),
                      RuntimeError('HTTP 403'), ValueError('invalid JSON')):
            with patch.object(scan, 'api', side_effect=error) as api, patch.object(scan.time, 'sleep') as sleep:
                with self.assertRaises(type(error)):
                    scan.osv_query('https://api.osv.dev/v1/vulns/GO-1')
                self.assertEqual(1, api.call_count)
                sleep.assert_not_called()

    def test_osv_retries_cannot_be_used_for_platform_writes(self):
        with patch.object(scan, 'api') as api:
            with self.assertRaises(ValueError):
                scan.osv_query('https://api.cnb.cool/repo/-/issues', 'POST', {})
            api.assert_not_called()

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

    def report(self, findings, packages=None, version='go1.26.8', pins=None):
        return {'findings': list(findings), 'packages': packages if packages is not None else [self.finding()],
                'unscanned': [],
                'toolchain': {'core/go.mod': {'version': version, 'language': '1.26',
                                              'pins': pins if pins is not None else {'pins': [version]}}}}

    def test_partial_group_repair_must_improve_without_new_risks(self):
        a = self.finding()
        b = self.finding('GO-2', ['CVE-2026-2222'])
        base = self.report([a, b])
        scan.require_group_progress(base, self.report([b]), 'go-core')
        for head in (base, self.report([self.finding('GO-3', ['CVE-2026-3333'])]),
                     {'findings': [], 'unscanned': [a], 'packages': [a], 'toolchain': base['toolchain']}):
            with self.assertRaises(ValueError):
                scan.require_group_progress(base, head, 'go-core')

    def test_toolchain_upgrade_counts_as_group_progress_without_removing_a_match(self):
        a = self.finding()
        base = self.report([a], version='go1.26.4')
        moved = dict(self.report([a], version='go1.26.8'), findings=[dict(a, version='v1.0.1')])
        scan.require_group_progress(base, moved, 'go-core')

    def test_a_lowered_toolchain_pin_is_not_group_progress(self):
        # The headline version is the highest pin, so lowering one pin while
        # raising another must not read as an upgrade.
        pins = {'.cnb.yml': ['1.26.4'], '.cnb/Dockerfile': ['1.26.8']}
        base = self.report([self.finding()], version='1.26.8', pins=pins)
        lowered = self.report([self.finding()], version='1.26.8',
                              pins={'.cnb.yml': ['1.24.0'], '.cnb/Dockerfile': ['1.26.8']})
        self.assertFalse(scan.toolchain_moved(base, lowered))
        with self.assertRaises(ValueError):
            scan.require_group_progress(base, lowered, 'go-core')

    def test_a_removed_toolchain_pin_is_not_group_progress(self):
        base = self.report([self.finding()], version='1.26.4', pins={'.cnb.yml': ['1.26.4']})
        dropped = self.report([self.finding()], version='1.26.8', pins={})
        self.assertFalse(scan.toolchain_moved(base, dropped))
        with self.assertRaises(ValueError):
            scan.require_group_progress(base, dropped, 'go-core')

    def test_every_pin_may_not_move_backwards(self):
        moved = self.report([self.finding()], version='1.26.8',
                            pins={'.cnb.yml': ['1.26.8'], '.cnb/Dockerfile': ['1.26.8']})
        mixed = self.report([self.finding()], version='1.26.8',
                            pins={'.cnb.yml': ['1.26.8'], '.cnb/Dockerfile': ['1.24.0']})
        base = self.report([self.finding()], version='1.26.4',
                           pins={'.cnb.yml': ['1.26.4'], '.cnb/Dockerfile': ['1.26.4']})
        self.assertFalse(scan.toolchain_moved(base, mixed))
        self.assertTrue(scan.toolchain_moved(base, moved))

    def test_an_unreadable_toolchain_version_is_not_group_progress(self):
        base = self.report([self.finding()], version='go1.26.4')
        for version in ('', 'devel go1.27-abc'):
            changed = self.report([self.finding()], version=version, pins={'pins': [version]})
            self.assertFalse(scan.toolchain_moved(base, changed))
            with self.assertRaises(ValueError):
                scan.require_group_progress(base, changed, 'go-core')

    def test_pinned_toolchain_is_read_from_the_tree_not_the_ambient_go(self):
        # A baseline and a PR scan share one image, so GOVERSION cannot tell them
        # apart; only the versions pinned in the tree can prove a toolchain move.
        with patch.object(scan.subprocess, 'run', return_value=Mock(stdout='{"GoVersion":"1.26"}')), \
                patch.object(scan.pathlib.Path, 'is_file', return_value=True), \
                patch.object(scan.pathlib.Path, 'read_text', side_effect=lambda *a, **k: 'image: golang:1.26.8'):
            toolchain = scan.core_toolchain(scan.pathlib.Path('.'))
        self.assertEqual({'core/go.mod': {'version': '1.26.8', 'language': '1.26',
                                          'pins': {'.cnb.yml': ['1.26.8']}}}, {'core/go.mod': toolchain})

    def test_placeholder_go_version_pins_are_not_read_as_a_version(self):
        with patch.object(scan.subprocess, 'run', return_value=Mock(stdout='{"GoVersion":"1.26"}')), \
                patch.object(scan.pathlib.Path, 'is_file', return_value=True), \
                patch.object(scan.pathlib.Path, 'read_text',
                             side_effect=lambda *a, **k: "go-version: ${{ env.GO_VERSION }}"):
            toolchain = scan.core_toolchain(scan.pathlib.Path('.'))
        self.assertEqual('', toolchain['version'])
        self.assertEqual({}, toolchain['pins'])

    def test_unchanged_group_scan_is_still_rejected(self):
        base = self.report([self.finding()])
        with self.assertRaises(ValueError):
            scan.require_group_progress(base, self.report([self.finding()]), 'go-core')

    def test_missing_go_inventory_cannot_pass_as_progress(self):
        a = self.finding()
        base = self.report([a], version='go1.26.4')
        for head in (self.report([a], packages=[], version='go1.26.8'),):
            with self.assertRaises(ValueError):
                scan.toolchain_moved(base, head)
            with self.assertRaises(ValueError):
                scan.require_group_progress(base, head, 'go-core')

    def test_a_toolchain_move_still_needs_readable_pins(self):
        base = self.report([self.finding()], version='go1.26.4', pins={})
        moved = self.report([self.finding()], version='go1.26.8', pins={})
        self.assertFalse(scan.toolchain_moved(base, moved))

    def test_other_groups_keep_the_advisory_removal_requirement(self):
        item = {'file': 'services/helper/Cargo.lock', 'ecosystem': 'crates.io', 'name': 'tokio',
                'version': '1.0.0', 'id': 'RUSTSEC-1', 'aliases': ['RUSTSEC-1'], 'fixed': ['1.0.1']}
        base = {'findings': [item], 'packages': [item], 'unscanned': [],
                'toolchain': {'core/go.mod': {'version': 'go1.26.4', 'language': '1.26'}}}
        moved = {**base, 'toolchain': {'core/go.mod': {'version': 'go1.26.8', 'language': '1.26'}}}
        with self.assertRaises(ValueError):
            scan.require_group_progress(base, moved, 'rust-helper')

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
