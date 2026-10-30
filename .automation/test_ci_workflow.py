import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/ci.yml'
ACTION = ROOT / '.github/actions/setup-android-toolchain/action.yml'
BUILD = ROOT / '.github/workflows/build.yaml'
SUMMARY = 'ci-ok'
TOOLCHAIN = (r"go-version: '([^']+)'", r"java-version: '([^']+)'", r"flutter-version: '([^']+)'",
             r'ndk-version: (\S+)', r'rustup toolchain install (\S+)')
# What CNB runs today (.cnb.yml:26-202), in the commands of the GitHub jobs that replace it.
CNB_COMMANDS = {
    'automation': ("python3 -m unittest discover -s .automation -p 'test_*.py'",),
    'go': ('go test . ./internal/logstore', 'go vet . ./internal/logstore',
           'GOOS=android GOARCH=arm64', 'go vet -tags="$tags" $pkgs'),
    'rust': ('cargo test --locked --manifest-path services/helper/Cargo.toml',
             'cargo test --locked --manifest-path plugins/rust_api/rust/Cargo.toml'),
    'flutter': ('flutter analyze --no-fatal-infos', 'flutter test --reporter expanded'),
    'android-unit-tests': (':common:testDebugUnitTest', ':service:testDebugUnitTest', ':app:testDebugUnitTest'),
}


def load_changes():
    spec = importlib.util.spec_from_file_location('ci_changes', ROOT / '.github/scripts/ci_changes.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


changes = load_changes()


def section(source, key):
    """Return the lines nested under a top-level key, read as plain text so it works without yaml."""
    match = re.search(rf'^{key}:\n((?:[ #].*\n|\n)*)', source, re.M)
    return match.group(1) if match else ''


def jobs(source):
    """Map each job id to its block."""
    parts = re.split(r'^  ([\w-]+):\n', section(source, 'jobs'), flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def job_field(block, field):
    match = re.search(rf'^    {field}: (.+)$', block, re.M)
    return match.group(1).strip() if match else None


def job_needs(block):
    value = job_field(block, 'needs') or '[]'
    return {item.strip() for item in value.strip('[]').split(',') if item.strip()}


class CiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding='utf-8')
        cls.action = ACTION.read_text(encoding='utf-8')
        cls.jobs = jobs(cls.source)

    def test_summary_job_needs_every_other_job(self):
        self.assertEqual(set(self.jobs) - {SUMMARY}, job_needs(self.jobs[SUMMARY]))

    def test_summary_job_always_runs_under_the_required_check_name(self):
        block = self.jobs[SUMMARY]
        self.assertEqual('always()', job_field(block, 'if'))
        self.assertEqual(SUMMARY, job_field(block, 'name'))
        others = [job_field(item, 'name') for name, item in self.jobs.items() if name != SUMMARY]
        self.assertNotIn(SUMMARY, others)

    def test_summary_job_fails_on_anything_but_success_or_skipped(self):
        script = re.search(r"jq -e '([^']+)'", self.jobs[SUMMARY]).group(1)
        self.assertEqual('all(.[]; .result == "success" or .result == "skipped")', script)
        if not shutil.which('jq'):
            self.skipTest('no jq')
        for results, code in ((['success', 'skipped'], 0), (['success', 'failure'], 1), (['cancelled', 'skipped'], 1)):
            payload = json.dumps({f'job{i}': {'result': item} for i, item in enumerate(results)})
            with self.subTest(results=results):
                run = subprocess.run(['jq', '-e', script], input=payload, text=True, capture_output=True)
                self.assertEqual(code, run.returncode)

    def test_triggers_are_only_pull_request_and_manual(self):
        self.assertEqual(['pull_request', 'workflow_dispatch'], re.findall(r'^  ([\w-]+):', section(self.source, 'on'), re.M))
        self.assertNotIn('pull_request_target', self.source)

    def test_permissions_are_read_only_and_never_widened(self):
        self.assertEqual('  contents: read\n', section(self.source, 'permissions'))
        self.assertEqual(1, len(re.findall(r'permissions:', self.source)))

    def test_no_secret_or_signing_material_reaches_pull_requests(self):
        for path, text in ((WORKFLOW, self.source), (ACTION, self.action)):
            with self.subTest(path=path.name):
                self.assertNotRegex(text, r'secrets[.:\[]')
                self.assertNotIn('inherit', text)
                for word in ('KEYSTORE', 'keystore', 'sign-apk', 'upload-artifact'):
                    self.assertNotIn(word, text)

    def test_runs_of_one_pull_request_cancel_each_other(self):
        block = section(self.source, 'concurrency')
        self.assertIn('github.event.pull_request.number', block)
        self.assertIn('cancel-in-progress: true', block)

    def test_actions_are_pinned_to_a_version_or_local(self):
        for use in re.findall(r'uses: (\S+)', self.source + self.action):
            with self.subTest(use=use):
                self.assertRegex(use, r'^(\./\.github/actions/[\w-]+|[\w-]+/[\w/-]+@v\d[\w.]*)$')

    def test_checkouts_keep_no_token(self):
        for block in re.findall(r'uses: actions/checkout@\S+\n((?:\s+.*\n)*?)(?=\s+- |\Z)', self.source):
            self.assertIn('persist-credentials: false', block)

    def test_toolchain_matches_the_release_build(self):
        build = BUILD.read_text(encoding='utf-8')
        for pattern in TOOLCHAIN:
            with self.subTest(pattern=pattern):
                expected = re.findall(pattern, build)
                self.assertEqual(1, len(set(expected)), expected)
                found = re.findall(pattern, self.action + self.source)
                self.assertTrue(found)
                self.assertEqual({expected[0]}, set(found))
        self.assertIn("RUSTUP_TOOLCHAIN: '1.99.0'", build)
        self.assertIn("RUSTUP_TOOLCHAIN: '1.99.0'", self.source)

    def test_every_cnb_check_has_a_github_job(self):
        for job, commands in CNB_COMMANDS.items():
            for command in commands:
                with self.subTest(job=job, command=command):
                    self.assertIn(command, self.jobs[job])

    def test_android_compile_matches_the_release_build(self):
        command = re.search(r'flutter build apk .+', BUILD.read_text(encoding='utf-8')).group(0)
        self.assertIn(command, self.jobs['android-build'])

    def test_job_conditions_read_outputs_the_script_writes(self):
        # A misspelt output is empty, the job is skipped, and a skipped job passes ci-ok.
        gated = {}
        for name, block in self.jobs.items():
            if name in ('changes', SUMMARY):
                continue
            self.assertEqual({'changes'}, job_needs(block), name)
            match = re.fullmatch(r"needs\.changes\.outputs\.(\w+) == 'true'", job_field(block, 'if') or '')
            self.assertIsNotNone(match, name)
            gated[name] = match.group(1)
        self.assertEqual(sorted(changes.JOBS), sorted(gated.values()))
        declared = re.findall(r'^      (\w+): \$\{\{ steps\.paths\.outputs\.(\w+) \}\}$', self.jobs['changes'], re.M)
        self.assertEqual(sorted((job, job) for job in changes.JOBS), sorted(declared))


class CiChangesTests(unittest.TestCase):
    def test_documentation_needs_no_job(self):
        self.assertEqual(set(), changes.needed_jobs(['docs/a.png', 'README.md', 'LICENSE', 'snapshots/x']))

    def test_markdown_counts_as_documentation_only_at_the_root(self):
        self.assertEqual(set(changes.JOBS), changes.needed_jobs(['plugins/x/README.md']))
        self.assertEqual({'automation', 'flutter', 'android_build'}, changes.needed_jobs(['assets/data/a.md']))

    def test_unknown_paths_run_every_job(self):
        for path in ('pubspec.yaml', 'plugins/rust_api/rust/src/lib.rs', 'tool/changelog.dart', '.github/release.json',
                     '.github/actions/setup-android-toolchain/action.yml', '.github/scripts/ci_changes.py',
                     'something/new', '"quoted'):
            with self.subTest(path=path):
                self.assertEqual(set(changes.JOBS), changes.needed_jobs([path]))

    def test_this_workflow_runs_every_job_but_other_workflows_do_not(self):
        self.assertEqual(set(changes.JOBS), changes.needed_jobs(['.github/workflows/ci.yml']))
        self.assertEqual({'automation'}, changes.needed_jobs(['.github/workflows/build.yaml']))

    def test_each_area_runs_its_jobs(self):
        cases = {
            '.automation/control.py': {'automation'},
            '.cnb.yml': {'automation'},
            'core/main.go': {'automation', 'go', 'android_unit', 'android_build'},
            'core/Clash.Meta': {'automation', 'go', 'android_unit', 'android_build'},
            'services/helper/src/main.rs': {'automation', 'rust'},
            'android/app/build.gradle.kts': {'automation', 'flutter', 'android_unit', 'android_build'},
            'lib/main.dart': {'automation', 'flutter', 'android_build'},
            'test/a_test.dart': {'automation', 'flutter'},
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(expected, changes.needed_jobs([path]))

    def test_a_rename_counts_both_sides(self):
        with tempfile.TemporaryDirectory() as root:
            def git(*args):
                command = ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args]
                subprocess.run(command, cwd=root, check=True, capture_output=True)
            git('init', '-q')
            pathlib.Path(root, 'core').mkdir()
            pathlib.Path(root, 'docs').mkdir()
            pathlib.Path(root, 'core/a.go').write_text('package a\n' * 20, encoding='utf-8')
            git('add', 'core')
            git('commit', '-qm', 'one')
            git('mv', 'core/a.go', 'docs/a.go')
            git('commit', '-qm', 'two')
            self.assertEqual(['core/a.go', 'docs/a.go'], changes.changed_paths('HEAD^1', 'HEAD', cwd=root))


if __name__ == '__main__':
    unittest.main()
