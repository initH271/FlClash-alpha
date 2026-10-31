import contextlib
import io
import json
import os
import pathlib
import ssl
import tempfile
import unittest
import urllib.error
from unittest.mock import call, patch

import control
import env_failure
import security_scan as scan
import security_watch as watch
from security_groups import payload_for

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Clock:
    """Monotonic time the network retries can advance without waiting."""

    def __init__(self, start=1000.0):
        self.now = start
        self.elapsed = 0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        self.elapsed += seconds


class SecurityTests(unittest.TestCase):
    def test_osv_timeout_retries_read_query_without_changing_payload(self):
        payload = {'queries': []}
        clock = Clock(start=1000.0)
        with patch.object(scan, 'api', side_effect=[TimeoutError(), {'results': []}]) as api, \
                patch.object(scan.time, 'monotonic', clock), \
                patch.object(scan.time, 'sleep', side_effect=clock.advance) as sleep:
            self.assertEqual({'results': []}, scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', payload,
                                                             until=1300.0))
            self.assertEqual(2, api.call_count)
            self.assertEqual(call('https://api.osv.dev/v1/querybatch', 'POST', payload, timeout=20),
                             api.call_args_list[1])
            self.assertEqual([call(5)], sleep.call_args_list)

    def test_osv_wrapped_timeout_retries_without_changing_payload(self):
        payload = {'queries': []}
        clock = Clock(start=1000.0)
        failure = urllib.error.URLError(TimeoutError('timed out'))
        with patch.object(scan, 'api', side_effect=[failure, {'results': []}]) as api, \
                patch.object(scan.time, 'monotonic', clock), \
                patch.object(scan.time, 'sleep', side_effect=clock.advance) as sleep:
            self.assertEqual({'results': []}, scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', payload,
                                                             until=1300.0))
            self.assertEqual(call('https://api.osv.dev/v1/querybatch', 'POST', payload, timeout=20),
                             api.call_args_list[1])
            self.assertEqual([call(5)], sleep.call_args_list)

    def test_osv_tls_eof_retries_without_changing_payload(self):
        payload = {'queries': []}
        clock = Clock(start=1000.0)
        failure = urllib.error.URLError(ssl.SSLEOFError('connection closed'))
        with patch.object(scan, 'api', side_effect=[failure, {'results': []}]) as api, \
                patch.object(scan.time, 'monotonic', clock), patch.object(scan.time, 'sleep', clock.advance):
            self.assertEqual({'results': []}, scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', payload,
                                                             until=1300.0))
            self.assertEqual(2, api.call_count)
            self.assertEqual(api.call_args_list[0], api.call_args_list[1])

    def test_osv_timeout_is_what_is_left_after_the_wait(self):
        clock = Clock(start=1000.0)
        with patch.object(scan, 'api', side_effect=[TimeoutError(), TimeoutError(), {'results': []}]) as api, \
                patch.object(scan.time, 'monotonic', clock), patch.object(scan.time, 'sleep', clock.advance):
            # 1000 -> 1005 leaves 30s: capped at 20. 1005 -> 1025 leaves 10s: not capped.
            self.assertEqual({'results': []}, scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', {},
                                                             until=1035.0))
        self.assertEqual([20, 20, 10], [item.kwargs['timeout'] for item in api.call_args_list])

    def test_osv_request_timeout_after_a_wait_shorter_than_the_cap(self):
        clock = Clock(start=1000.0)
        # 1030 leaves 25s at 1005, so the 5s wait is taken; 1005 -> 1010 leaves 20s exactly.
        with patch.object(scan, 'api', side_effect=[TimeoutError(), {'results': []}]) as api, \
                patch.object(scan.time, 'monotonic', clock), \
                patch.object(scan.time, 'sleep', side_effect=clock.advance) as sleep:
            self.assertEqual({'results': []}, scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', {},
                                                             until=1030.0))
        self.assertEqual([call(5)], sleep.call_args_list)
        self.assertEqual([20, 20], [item.kwargs['timeout'] for item in api.call_args_list])

    def test_osv_request_timeout_floors_the_time_left_before_the_deadline(self):
        clock = Clock(start=1000.0)
        # 1017.9 leaves 17.9s after the wait: the request gets 17, not 18.
        with patch.object(scan, 'api', side_effect=[TimeoutError(), {'results': []}]) as api, \
                patch.object(scan.time, 'monotonic', clock), \
                patch.object(scan.time, 'sleep', side_effect=clock.advance) as sleep:
            self.assertEqual({'results': []}, scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', {},
                                                             until=1017.9))
        self.assertEqual([call(5)], sleep.call_args_list)
        self.assertEqual([17, 12], [item.kwargs['timeout'] for item in api.call_args_list])
        self.assertGreater(1017.9 - clock.now, 12)

    def test_osv_exhausted_network_retries_fail_instead_of_reporting_clean(self):
        clock = Clock(start=1000.0)
        with patch.object(scan, 'api', side_effect=TimeoutError) as api, \
                patch.object(scan.time, 'monotonic', clock), \
                patch.object(scan.time, 'sleep', side_effect=clock.advance) as sleep:
            with self.assertRaises(scan.EnvironmentFailure) as raised:
                scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', {}, until=1000.0 + 300)
            self.assertEqual(5, api.call_count)
            self.assertEqual([call(5), call(20), call(60), call(180)], sleep.call_args_list)
        self.assertEqual('osv-unreachable', raised.exception.kind)
        self.assertEqual(5, raised.exception.detail['attempts'])

    def test_osv_gives_up_before_the_deadline_cannot_cover_the_next_wait(self):
        clock = Clock(start=1000.0)
        with patch.object(scan, 'api', side_effect=TimeoutError) as api, \
                patch.object(scan.time, 'monotonic', clock), patch.object(scan.time, 'sleep', clock.advance):
            with self.assertRaises(scan.EnvironmentFailure):
                scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', {}, until=1006)
        # The 5s wait still leaves a request; the 20s one would not.
        self.assertEqual(2, api.call_count)
        self.assertEqual(5, clock.elapsed)
        self.assertEqual([1], [item.kwargs['timeout'] for item in api.call_args_list[1:]])

    def test_osv_retries_server_errors_but_not_other_http_or_application_errors(self):
        failure = scan.HttpStatusError('POST api.osv.dev returned HTTP 503: unavailable', 503)
        with patch.object(scan, 'api', side_effect=[failure, {'results': []}]) as api, \
                patch.object(scan.time, 'sleep'):
            self.assertEqual({'results': []}, scan.osv_query('https://api.osv.dev/v1/querybatch', 'POST', {}))
            self.assertEqual(2, api.call_count)
        for error in (urllib.error.URLError(ssl.SSLCertVerificationError('invalid certificate')),
                      scan.HttpStatusError('GET api.osv.dev returned HTTP 403: forbidden', 403),
                      ValueError('invalid JSON')):
            with patch.object(scan, 'api', side_effect=error) as api, \
                    patch.object(scan.time, 'sleep') as sleep:
                with self.assertRaises(type(error)) as raised:
                    scan.osv_query('https://api.osv.dev/v1/vulns/GO-1')
                self.assertEqual(1, api.call_count)
                sleep.assert_not_called()
                self.assertNotIsInstance(raised.exception, scan.EnvironmentFailure)

    def test_osv_retries_cannot_be_used_for_platform_writes(self):
        with patch.object(scan, 'api') as api:
            with self.assertRaises(ValueError):
                scan.osv_query('https://api.cnb.cool/repo/-/issues', 'POST', {})
            api.assert_not_called()

    def test_osv_unreachable_scan_marks_the_environment_and_exits_with_75(self):
        report = pathlib.Path(tempfile.mkdtemp()) / 'report.json'
        with patch.object(scan, 'api', side_effect=TimeoutError), \
                patch.object(scan.time, 'sleep'), \
                patch.object(scan.time, 'monotonic', Clock()), \
                patch.object(scan, 'inventory', return_value=([{'file': 'core/go.mod', 'ecosystem': 'Go',
                                                               'name': 'example.org/module', 'version': 'v1.0.0'}],
                                                              [])), \
                patch.object(scan, 'head_sha', return_value='a' * 40), \
                patch.dict(os.environ, {'FLCLASH_NETWORK_DEADLINE': '0'}), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = scan.main([str(ROOT), str(report)])
        self.assertEqual(75, code)
        self.assertNotEqual(0, code)
        self.assertEqual(1, stdout.getvalue().count(env_failure.MARKER))
        [marker] = env_failure.parse(stdout.getvalue())
        self.assertEqual('osv-unreachable', marker['kind'])
        self.assertEqual('a' * 40, marker['sha'])
        self.assertFalse(report.exists())

    def test_osv_unreachable_main_retries_five_times_then_exits_with_75(self):
        report = pathlib.Path(tempfile.mkdtemp()) / 'report.json'
        clock = Clock(start=1000.0)
        with patch.object(scan, 'api', side_effect=TimeoutError) as api, \
                patch.object(scan.time, 'monotonic', clock), patch.object(scan.time, 'sleep', clock.advance), \
                patch.object(scan, 'inventory', return_value=([{'file': 'core/go.mod', 'ecosystem': 'Go',
                                                               'name': 'example.org/module', 'version': 'v1.0.0'}],
                                                              [])), \
                patch.object(scan, 'head_sha', return_value='b' * 40), \
                patch.dict(os.environ, {'FLCLASH_NETWORK_DEADLINE': '1300'}), \
                patch.object(scan.time, 'time', return_value=0.0), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = scan.main([str(ROOT), str(report)])
        self.assertEqual(75, code)
        self.assertEqual(5, api.call_count)
        self.assertEqual(1, stdout.getvalue().count(env_failure.MARKER))
        self.assertEqual('osv-unreachable', env_failure.parse(stdout.getvalue())[0]['kind'])
        self.assertFalse(report.exists())

    def test_new_findings_still_fail_without_an_environment_marker(self):
        reports = pathlib.Path(tempfile.mkdtemp())
        baseline, output = reports / 'baseline.json', reports / 'head.json'
        baseline.write_text(json.dumps({'findings': [], 'packages': [], 'unscanned': [], 'toolchain': {}}))
        report = {'findings': [self.finding()], 'packages': [self.finding()], 'unscanned': [], 'toolchain': {}}
        with patch.object(scan, 'scan', return_value=report), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = scan.main([str(ROOT), str(output), '--baseline', str(baseline)])
        self.assertNotIn(code, (0, 75))
        self.assertNotIn(env_failure.MARKER, stdout.getvalue())
        self.assertTrue(output.exists())

    def test_environment_marker_parsing_ignores_anything_but_its_own_line(self):
        text = json.dumps({'kind': 'osv-unreachable'})
        self.assertEqual([], env_failure.parse(f'log {env_failure.MARKER} {text}'))
        self.assertEqual([], env_failure.parse(f'{env_failure.MARKER} {{not json'))
        self.assertEqual([], env_failure.parse(f'{env_failure.MARKER} {{"attempts": 5}}'))
        self.assertEqual([{'kind': 'osv-unreachable'}], env_failure.parse(f'{env_failure.MARKER} {text}'))
        self.assertEqual(75, env_failure.EXIT_CODE)
        self.assertNotIn('\n', env_failure.line('osv-unreachable', url='u', attempts=5))

    def test_control_reports_http_status_as_a_typed_error(self):
        error = urllib.error.HTTPError('https://api.github.com/x', 502, 'bad gateway', None,
                                       io.BytesIO(b'{"message": "bad gateway"}'))
        with patch.object(control.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(control.HttpStatusError) as raised:
                control.api('https://api.github.com/repos/x/y')
        self.assertIsInstance(raised.exception, RuntimeError)
        self.assertEqual(502, raised.exception.code)
        self.assertEqual('GET api.github.com returned HTTP 502: bad gateway', str(raised.exception))

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
        with patch.object(scan.pathlib.Path, 'is_file', return_value=True), \
                patch.object(scan.pathlib.Path, 'read_text', side_effect=lambda *a, **k: 'image: golang:1.26.8'):
            toolchain = scan.core_toolchain(scan.pathlib.Path('.'))
        self.assertEqual({'version': '1.26.8', 'pins': {'.cnb.yml': ['1.26.8']}}, toolchain)

    def test_developer_image_pins_the_same_go_as_the_ci_image(self):
        pins = scan.core_toolchain(scan.pathlib.Path(__file__).resolve().parents[1])['pins']
        self.assertEqual(pins['.cnb/Dockerfile'], pins['.cnb/npc.Dockerfile'])

    def test_placeholder_go_version_pins_are_not_read_as_a_version(self):
        with patch.object(scan.pathlib.Path, 'is_file', return_value=True), \
                patch.object(scan.pathlib.Path, 'read_text',
                             side_effect=lambda *a, **k: "go-version: ${{ env.GO_VERSION }}"):
            toolchain = scan.core_toolchain(scan.pathlib.Path('.'))
        self.assertEqual('', toolchain['version'])
        self.assertEqual({}, toolchain['pins'])

    def test_a_new_pin_below_the_advanced_version_is_not_progress(self):
        base = self.report([self.finding()], version='1.26.4', pins={'.cnb.yml': ['1.26.4']})
        low = self.report([self.finding()], version='1.26.8',
                          pins={'.cnb.yml': ['1.26.8'], '.cnb/Dockerfile': ['1.20.0']})
        matched = self.report([self.finding()], version='1.26.8',
                              pins={'.cnb.yml': ['1.26.8'], '.cnb/Dockerfile': ['1.26.8']})
        self.assertFalse(scan.toolchain_moved(base, low))
        self.assertTrue(scan.toolchain_moved(base, matched))

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
