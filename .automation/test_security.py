import contextlib
import io
import json
import os
import pathlib
import re
import ssl
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import call, patch

import control
import env_failure
import security_scan as scan

ROOT = pathlib.Path(__file__).resolve().parents[1]


def marker_of(text):
    row = next(line for line in text.splitlines() if line.startswith(env_failure.MARKER + ' '))
    return json.loads(row[len(env_failure.MARKER) + 1:])


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
        marker = marker_of(stdout.getvalue())
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
        self.assertEqual('osv-unreachable', marker_of(stdout.getvalue())['kind'])
        self.assertFalse(report.exists())

    def test_new_findings_still_fail_without_an_environment_marker(self):
        reports = pathlib.Path(tempfile.mkdtemp())
        baseline, output = reports / 'baseline.json', reports / 'head.json'
        baseline.write_text(json.dumps({'findings': [], 'packages': [], 'unscanned': []}))
        report = {'findings': [self.finding()], 'packages': [self.finding()], 'unscanned': []}
        with patch.object(scan, 'scan', return_value=report), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = scan.main([str(ROOT), str(output), '--baseline', str(baseline)])
        self.assertNotIn(code, (0, 75))
        self.assertNotIn(env_failure.MARKER, stdout.getvalue())
        self.assertTrue(output.exists())

    def test_environment_marker_is_one_line_with_its_own_exit_code(self):
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

    def test_concatenated_go_module_json_is_parsed(self):
        self.assertEqual([{'Path': 'a'}, {'Path': 'b'}], list(scan.json_stream(' {"Path":"a"}\n {"Path":"b"}\n')))

    def test_the_scan_never_reads_a_pipeline_file_for_a_toolchain_pin(self):
        self.assertFalse(hasattr(scan, 'TOOLCHAIN_PINS'))
        self.assertFalse(hasattr(scan, 'require_group_progress'))


class SecurityWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / '.github/workflows/security.yaml').read_text(encoding='utf-8')

    def test_the_required_check_keeps_its_name_and_is_the_only_job(self):
        self.assertEqual(['scan'], re.findall(r'^  ([\w-]+):$', self.source.split('jobs:\n')[1], re.M))
        self.assertIn('    name: Dependency vulnerability scan\n', self.source)

    def test_it_needs_nothing_a_dependabot_or_fork_pr_lacks(self):
        self.assertNotIn('secrets.', self.source)
        self.assertIn('permissions:\n  contents: read\nconcurrency:', self.source)
        self.assertNotRegex(self.source, r'CNB|security_watch|APPROVAL')

    def test_a_pr_still_compares_base_and_head_with_the_scanner_from_main(self):
        self.assertIn('types: [opened, reopened, synchronize]', self.source)
        self.assertIn('security_scan.py source security-report.json --baseline baseline-security.json', self.source)
        self.assertIn('security_scan.py baseline baseline-security.json', self.source)
        self.assertIn('ref: main\n          path: tools', self.source)
        self.assertRegex(self.source, r"cron: '")
        self.assertIn('branches: [main]', self.source)

    def test_the_tracking_issues_are_gone(self):
        for name in ('security_watch.py', 'security_groups.py'):
            self.assertFalse((ROOT / '.automation' / name).exists())
        for path in (ROOT / '.automation').glob('*.py'):
            if not path.name.startswith('test_'):
                self.assertNotIn('安全修复', path.read_text(encoding='utf-8'), path.name)


class DependabotTests(unittest.TestCase):
    """Read as plain text so it works without yaml: a block is the lines under one package-ecosystem."""

    MANIFESTS = {'pub': ('pubspec.yaml',), 'gomod': ('go.mod',), 'cargo': ('Cargo.toml',),
                 'gradle': ('settings.gradle.kts', 'build.gradle', 'build.gradle.kts'), 'github-actions': ('action.yml', '.github/workflows'),
                 'gitsubmodule': ('.gitmodules',)}

    def setUp(self):
        self.source = (ROOT / '.github/dependabot.yml').read_text(encoding='utf-8')
        parts = re.split(r'^  - package-ecosystem: (\S+)\n', self.source, flags=re.M)
        self.blocks = dict(zip(parts[1::2], parts[2::2]))

    def directories(self, block):
        return re.findall(r'^    directory: (\S+)$', block, re.M) + re.findall(r'^      - (/\S*)$', block, re.M)

    def test_every_ecosystem_is_listed_once(self):
        self.assertEqual(sorted(self.MANIFESTS), sorted(self.blocks))
        self.assertEqual(len(self.blocks), self.source.count('package-ecosystem:'))

    def test_every_directory_exists_and_holds_that_ecosystems_manifest(self):
        for ecosystem, block in self.blocks.items():
            directories = self.directories(block)
            self.assertTrue(directories, ecosystem)
            for directory in directories:
                with self.subTest(ecosystem=ecosystem, directory=directory):
                    self.assertTrue(any((ROOT / directory.lstrip('/') / name).exists() for name in self.MANIFESTS[ecosystem]))

    def test_every_rust_and_go_manifest_in_the_repository_is_covered(self):
        tracked = subprocess.run(['git', 'ls-files', '*go.mod', '*Cargo.toml'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        wanted = {'/' + str(pathlib.PurePath(path).parent) for path in tracked}
        self.assertEqual(wanted, set(self.directories(self.blocks['gomod'])) | set(self.directories(self.blocks['cargo'])))

    def test_the_submodules_own_go_mod_is_not_listed_because_it_is_not_in_this_repository(self):
        self.assertNotIn('Clash.Meta\n', self.source.split('updates:')[1])

    def test_it_cannot_flood(self):
        for ecosystem, block in self.blocks.items():
            with self.subTest(ecosystem=ecosystem):
                self.assertIn('interval: weekly', block)
                self.assertLessEqual(int(re.search(r'open-pull-requests-limit: (\d+)', block).group(1)), 2)
                if ecosystem != 'gitsubmodule':
                    self.assertEqual(2, block.count("patterns: ['*']"))

    def test_yaml_aliases_are_not_relied_on(self):
        self.assertNotRegex(self.source, r'[&*]\w+\s*$')
