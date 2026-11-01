import json
import os
import pathlib
import re
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import windows_release as w

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/windows.yaml').read_text(encoding='utf-8')
SHA = 'a' * 40
IDENTITY = {'tag': 'v0.9.2-alpha.21', 'displayVersion': '0.9.2-alpha.21', 'build': 2026094021}
VERSION = '0.9.2-alpha.21+2026094021'


def android_run(**changes):
    return {'conclusion': 'success', 'head_branch': 'main', 'head_sha': SHA, 'event': 'push',
            'head_repository': {'full_name': w.POLICY['github']}, **changes}


def release(*names, **changes):
    assets = [{'name': name} for name in ('FlClash-alpha-arm64-v8a.apk', w.CHECKSUMS, 'update.json', *names)]
    return {'tag_name': IDENTITY['tag'], 'draft': False, 'prerelease': False, 'target_commitish': SHA,
            'assets': assets, **changes}


def pe_with_version(version):
    pad = b'\0\0' if len(version) % 2 else b''
    return (b'MZ' + b'\0' * 64 + 'ProductVersion'.encode('utf-16-le') + b'\0\0' + b'\0\0'
            + version.encode('utf-16-le') + b'\0\0' + pad + 'Other'.encode('utf-16-le'))


def write_packages(directory, version=VERSION, skip=None):
    directory = pathlib.Path(directory)
    with zipfile.ZipFile(directory / w.ARCHIVE, 'w') as archive:
        for name in w.BUNDLE:
            if name != skip:
                archive.writestr(name, pe_with_version(version) if name == 'FlClash.exe' else b'x')
    (directory / w.SETUP).write_bytes(pe_with_version(version))


class PlanTests(unittest.TestCase):
    def plan_after_android(self, run, found):
        with patch.object(w, 'identity_at', return_value=IDENTITY), patch.object(w, 'release_by_tag', return_value=found):
            return w.plan_after_android(run)

    def test_the_run_that_published_the_release_leads_to_a_build(self):
        self.assertEqual({'mode': 'publish', 'source': SHA, 'tag': IDENTITY['tag']},
                         self.plan_after_android(android_run(), release()))

    def test_a_recovery_dispatch_also_counts(self):
        self.assertEqual('publish', self.plan_after_android(android_run(event='workflow_dispatch'), release())['mode'])

    def test_every_other_run_ends_cleanly_without_asking_github(self):
        for changes in ({'conclusion': 'failure'}, {'conclusion': 'cancelled'}, {'head_branch': 'dev'},
                        {'event': 'pull_request'}, {'head_repository': {'full_name': 'someone/fork'}},
                        {'head_repository': None}):
            with self.subTest(changes), patch.object(w, 'api', side_effect=AssertionError):
                self.assertEqual(w.SKIP, w.plan_after_android(android_run(**changes)))

    def test_a_merge_without_a_version_change_finds_another_target_and_skips(self):
        self.assertEqual(w.SKIP, self.plan_after_android(android_run(), release(target_commitish='b' * 40)))

    def test_no_release_or_a_draft_skips(self):
        self.assertEqual(w.SKIP, self.plan_after_android(android_run(), None))
        self.assertEqual(w.SKIP, self.plan_after_android(android_run(), release(draft=True)))

    def test_a_release_with_both_windows_files_skips_and_with_one_rebuilds(self):
        self.assertEqual(w.SKIP, self.plan_after_android(android_run(), release(w.SETUP, w.ARCHIVE)))
        self.assertEqual('publish', self.plan_after_android(android_run(), release(w.SETUP))['mode'])

    def retry(self, found, ref='refs/heads/main', identity=IDENTITY):
        with patch.object(w, 'identity_at', return_value=identity), patch.object(w, 'release_by_tag', return_value=found):
            return w.plan_retry(IDENTITY['tag'], ref)

    def test_a_manual_retry_builds_the_release_target(self):
        self.assertEqual({'mode': 'publish', 'source': SHA, 'tag': IDENTITY['tag']}, self.retry(release()))

    def test_a_manual_retry_refuses_what_it_cannot_do(self):
        for found, ref, identity in ((release(), 'refs/heads/dev', IDENTITY),
                                     (release(target_commitish='main'), 'refs/heads/main', IDENTITY),
                                     (release(draft=True), 'refs/heads/main', IDENTITY),
                                     (release(), 'refs/heads/main', {'tag': 'v0.9.2-alpha.20'})):
            with self.subTest(found=found, ref=ref), self.assertRaises(ValueError):
                self.retry(found, ref, identity)

    def test_a_manual_retry_of_a_finished_release_does_nothing(self):
        self.assertEqual(w.SKIP, self.retry(release(w.SETUP, w.ARCHIVE)))

    def test_pull_requests_and_plain_dispatches_only_compile(self):
        for event in ('pull_request', 'workflow_dispatch'):
            self.assertEqual({'mode': 'compile', 'source': SHA, 'tag': ''},
                             w.choose_plan(event, {}, '', 'refs/pull/1/merge', SHA))


class PackageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = pathlib.Path(directory.name)

    def test_the_pubspec_takes_the_release_version(self):
        (self.dir / '.github').mkdir()
        (self.dir / '.github/release.json').write_text(json.dumps(
            {'version': '0.9.2', 'upstreamVersion': '0.9.2', 'revision': 21, 'build': 2026094021,
             'displayVersion': '0.9.2-alpha.21'}))
        (self.dir / 'pubspec.yaml').write_text('name: fl_clash\nversion: 0.9.2+2026102401\nother: version: no\n')
        w.stamp(self.dir)
        self.assertEqual(f'name: fl_clash\nversion: {VERSION}\nother: version: no\n',
                         (self.dir / 'pubspec.yaml').read_text())

    def test_the_product_version_is_read_from_the_pe_string_table(self):
        self.assertEqual(VERSION, w.product_version(pe_with_version(VERSION)))
        self.assertIsNone(w.product_version(b'MZ no resources'))

    def test_complete_packages_pass(self):
        write_packages(self.dir)
        w.verify(self.dir, IDENTITY)

    def test_a_wrong_version_fails(self):
        write_packages(self.dir, version='0.9.2+2026102401')
        with self.assertRaisesRegex(ValueError, 'expected 0.9.2-alpha.21'):
            w.verify(self.dir, IDENTITY)

    def test_a_wrong_version_of_the_installer_fails(self):
        write_packages(self.dir)
        (self.dir / w.SETUP).write_bytes(pe_with_version('1.0.0'))
        with self.assertRaisesRegex(ValueError, 'setup.exe is version 1.0.0'):
            w.verify(self.dir, IDENTITY)

    def test_each_file_a_running_installation_needs_is_required(self):
        for name in w.BUNDLE[1:]:
            with self.subTest(name=name):
                write_packages(self.dir, skip=name)
                with self.assertRaisesRegex(ValueError, 'lacks'):
                    w.verify(self.dir, IDENTITY)

    def test_package_needs_exactly_one_of_each(self):
        (self.dir / 'dist').mkdir()
        with self.assertRaisesRegex(ValueError, 'Expected one'):
            w.package(self.dir)


class ChecksumTests(unittest.TestCase):
    APK = 'abc  FlClash-alpha-arm64-v8a.apk'

    def test_the_apk_line_stays_first_and_unchanged(self):
        self.assertEqual(f'{self.APK}\n1  {w.SETUP}\n2  {w.ARCHIVE}\n',
                         w.merge_checksums(self.APK + '\n', {w.SETUP: '1', w.ARCHIVE: '2'}))

    def test_merging_again_replaces_the_windows_lines(self):
        once = w.merge_checksums(self.APK + '\n', {w.SETUP: '1', w.ARCHIVE: '2'})
        self.assertEqual(f'{self.APK}\n3  {w.SETUP}\n4  {w.ARCHIVE}\n',
                         w.merge_checksums(once, {w.SETUP: '3', w.ARCHIVE: '4'}))

    def test_a_file_without_the_apk_line_is_refused(self):
        with self.assertRaises(ValueError):
            w.merge_checksums('', {w.SETUP: '1'})


class PublishTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = pathlib.Path(directory.name)
        (self.dir / w.OUTPUT).mkdir()
        write_packages(self.dir / w.OUTPUT)
        self.commands = []

    def gh(self, *args):
        self.commands.append(args)
        if args[1] == 'upload' and args[-2].endswith(w.CHECKSUMS):
            self.sums = pathlib.Path(args[-2]).read_text()
        return b'abc  FlClash-alpha-arm64-v8a.apk\n'

    def publish(self, found):
        env = {'TAG': IDENTITY['tag'], 'SOURCE': SHA}
        with patch.dict(os.environ, env), patch.object(w, 'gh', self.gh), patch.object(w, 'close_report'), \
                patch.object(w, 'identity_at', return_value=IDENTITY), patch.object(w, 'release_by_tag', return_value=found):
            w.publish(self.dir)

    def test_the_checksums_go_up_after_both_files(self):
        self.publish(release())
        uploads = [c for c in self.commands if c[1] == 'upload']
        self.assertEqual(2, len(uploads))
        self.assertTrue(uploads[0][3].endswith(w.SETUP) and uploads[0][4].endswith(w.ARCHIVE))
        self.assertTrue(uploads[1][3].endswith(w.CHECKSUMS))
        self.assertEqual('abc  FlClash-alpha-arm64-v8a.apk', self.sums.splitlines()[0])
        self.assertEqual([w.SETUP, w.ARCHIVE], [line.split()[-1] for line in self.sums.splitlines()[1:]])

    def test_only_uploads_ever_touch_the_release(self):
        self.publish(release())
        self.assertEqual({'download', 'upload'}, {c[1] for c in self.commands})

    def test_a_moved_target_or_a_draft_uploads_nothing(self):
        for found in (release(target_commitish='b' * 40), release(draft=True)):
            with self.subTest(found=found), self.assertRaises(ValueError):
                self.publish(found)
        self.assertEqual([], self.commands)

    def test_a_bad_package_uploads_nothing(self):
        write_packages(self.dir / w.OUTPUT, skip='FlClashCore.exe')
        with self.assertRaises(ValueError):
            self.publish(release())
        self.assertEqual([], self.commands)


class ReportTests(unittest.TestCase):
    ENV = {'GITHUB_RUN_ID': '7', 'GITHUB_SERVER_URL': 'https://github.com', 'GITHUB_REPOSITORY': 'o/r',
           'TAG': IDENTITY['tag']}

    def report(self, issues, env=None):
        with patch.dict(os.environ, {**self.ENV, **(env or {})}), patch.object(w, 'bot_issues', return_value=issues), \
                patch.object(w, 'api') as api, patch.object(w, 'comment_once') as comment_once:
            w.report()
        return api, comment_once

    def test_one_issue_per_release_assigned_to_the_owner_with_the_way_to_retry(self):
        api, _ = self.report([])
        body = api.call_args.args[2]
        self.assertEqual(f'[Windows 构建待处理] {IDENTITY["tag"]}', body['title'])
        self.assertEqual([w.OWNER], body['assignees'])
        self.assertIn('https://github.com/o/r/actions/runs/7', body['body'])
        self.assertIn('release_tag', body['body'])

    def test_a_second_failure_comments_on_the_open_issue(self):
        api, comment_once = self.report([{'title': f'[Windows 构建待处理] {IDENTITY["tag"]}', 'number': 5}])
        api.assert_not_called()
        self.assertEqual(5, comment_once.call_args.args[0])

    def test_a_failed_plan_has_no_tag_and_still_reports(self):
        api, _ = self.report([], {'TAG': ''})
        self.assertEqual('[Windows 构建待处理] 运行 7', api.call_args.args[2]['title'])

    def test_a_published_build_closes_its_issue(self):
        with patch.object(w, 'bot_issues', return_value=[{'title': w.issue_title('v1'), 'number': 5},
                                                         {'title': w.issue_title('v2'), 'number': 6}]), \
                patch.object(w, 'comment') as comment, patch.object(w, 'api') as api:
            w.close_report('v1')
        comment.assert_called_once()
        self.assertTrue(api.call_args.args[0].endswith('/issues/5'))

    def test_cleanup_never_fails_a_finished_publish(self):
        with patch.object(w, 'bot_issues', side_effect=RuntimeError('boom')):
            w.close_report('v1')


def job(name):
    return re.search(rf'^  {name}:\n((?:    .*\n|      .*\n|\n)+)', WORKFLOW, re.M).group(1)


class WorkflowTests(unittest.TestCase):
    def test_top_level_permissions_only_read(self):
        self.assertEqual(['contents: read'],
                         re.findall(r'^  (\w[\w-]*: \w+)$', WORKFLOW.split('permissions:\n')[1].split('concurrency:')[0], re.M))

    def test_only_publish_writes_contents(self):
        self.assertEqual(1, WORKFLOW.count('contents: write'))
        self.assertIn('contents: write', job('publish'))

    def test_no_compiling_job_sees_a_secret_or_keeps_a_credential(self):
        for name in ('plan', 'helper-test', 'build'):
            with self.subTest(name):
                self.assertNotIn('secrets.', job(name))
                self.assertNotIn('permissions:', job(name))
                self.assertIn('persist-credentials: false', job(name))
        self.assertEqual(['CNB_AUTOMATION_TOKEN'], re.findall(r'(\w+): \$\{\{ secrets\.', WORKFLOW))

    def test_the_mirror_start_cannot_fail_a_finished_publish(self):
        step = job('publish').split('Start the CNB mirror')[1]
        self.assertIn('continue-on-error: true', step)
        self.assertIn('control.py mirror', step)

    def test_the_trigger_follows_the_android_release_by_its_exact_name(self):
        name = re.search(r'^name: (.+)$', (ROOT / '.github/workflows/build.yaml').read_text(encoding='utf-8'), re.M).group(1)
        self.assertIn(f"workflows: ['{name}']", WORKFLOW)

    def test_no_event_text_reaches_a_shell(self):
        indent = None
        for line in WORKFLOW.splitlines():
            depth = len(line) - len(line.lstrip())
            if indent is not None and line.strip() and depth <= indent:
                indent = None
            if indent is not None or re.match(r'\s*(- )?run: ', line):
                self.assertNotIn('${{', line)
            if line.rstrip().endswith('run: |'):
                indent = depth

    def test_the_toolchain_matches_the_android_release(self):
        build = (ROOT / '.github/workflows/build.yaml').read_text(encoding='utf-8')
        for pattern in (r"go-version: '([^']+)'", r"flutter-version: '([^']+)'", r'rustup toolchain install (\S+)',
                        r"RUSTUP_TOOLCHAIN: '([^']+)'"):
            self.assertEqual(re.search(pattern, build).group(1), re.search(pattern, WORKFLOW).group(1), pattern)

    def test_windows_stays_out_of_the_required_checks(self):
        ci = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertNotIn('windows', ci.lower())

    def test_a_pull_request_never_reaches_publish_or_report(self):
        self.assertIn("github.event_name != 'pull_request'", job('report'))
        self.assertIn("needs.plan.outputs.mode == 'publish'", job('publish'))

    def test_every_packaged_name_is_the_one_the_mirror_copies(self):
        mirror = (ROOT / '.cnb/mirror-release.py').read_text(encoding='utf-8')
        self.assertIn(w.SETUP, mirror)
        self.assertIn(w.ARCHIVE, mirror)


if __name__ == '__main__':
    unittest.main()
