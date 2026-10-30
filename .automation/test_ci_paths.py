import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import ci_paths
import test_cnb_pipelines as cnb

SOURCE = cnb.CNB.read_text(encoding='utf-8')
STAGES = ('flutter', 'android', 'govet')
REUSE = 'python3 .automation/ci_paths.py reuse || [ $? -ne 3 ] || exit 0'


class FlutterTriggerTests(unittest.TestCase):
    def test_dart_and_flutter_build_inputs_always_trigger_the_flutter_stage(self):
        for path in ('lib/main.dart', 'lib/ui/deep/card.dart', 'test/app_test.dart', 'pubspec.yaml',
                     'pubspec.lock', 'android/app/build.gradle', '.cnb/Dockerfile', 'plugins/rust_api/lib/a.dart'):
            self.assertTrue(ci_paths.triggers('flutter', [path], SOURCE, SOURCE), path)
        self.assertTrue(ci_paths.triggers('android', ['core/hub.go'], SOURCE, SOURCE))
        self.assertTrue(ci_paths.triggers('govet', ['build_config.yaml'], SOURCE, SOURCE))

    def test_automation_and_docs_changes_trigger_no_flutter_stage(self):
        for stage in STAGES:
            self.assertFalse(ci_paths.triggers(stage, ['.automation/wake.py', 'README.md', 'docs/a.md',
                                                       'tool/hooks/x.sh', '.github/w.yml'], SOURCE, SOURCE))

    def test_cnb_yml_triggers_only_when_the_flutter_pipeline_block_changed(self):
        outside = SOURCE.replace("echo 'Skipped: no automation changes'", "echo 'Skipped: nothing to test'")
        inside = SOURCE.replace('          timeout: 45m\n', '          timeout: 50m\n')
        self.assertNotEqual(SOURCE, outside)
        self.assertNotEqual(SOURCE, inside)
        for stage in STAGES:
            self.assertFalse(ci_paths.triggers(stage, ['.cnb.yml'], SOURCE, outside), stage)
            self.assertTrue(ci_paths.triggers(stage, ['.cnb.yml'], SOURCE, inside), stage)

    def test_an_unlocatable_or_aliased_flutter_block_keeps_triggering(self):
        renamed = SOURCE.replace(f'name: {ci_paths.FLUTTER}\n', 'name: Flutter tests\n')
        self.assertNotEqual(SOURCE, renamed)
        aliased = SOURCE.replace('      runner: { cpus: 4 }\n      docker:\n        image: ubuntu:24.04',
                                 '      runner: *big\n      docker:\n        image: ubuntu:24.04')
        outside = SOURCE.replace("echo 'Skipped: no automation changes'", "echo 'Skipped'")
        self.assertNotEqual(SOURCE, aliased)
        for old, new in ((renamed, renamed.replace("echo 'Skipped: no automation changes'", "echo 'x'")),
                         (aliased, aliased.replace("echo 'Skipped: no automation changes'", "echo 'x'")),
                         ('', outside)):
            self.assertTrue(ci_paths.triggers('flutter', ['.cnb.yml'], old, new))

    def test_the_anchored_flutter_entry_is_located_and_owner_edits_leave_it_alone(self):
        block = ci_paths.flutter_block(SOURCE)
        self.assertRegex(block.split('\n')[0], r'^\s*- &[\w-]+$')
        self.assertIn(f'name: {ci_paths.FLUTTER}', block)
        self.assertIn('timeout: 45m', block)
        shrunk = SOURCE.replace('    - *rust-tests\n', '')
        self.assertNotEqual(SOURCE, shrunk)
        for stage in STAGES:
            self.assertFalse(ci_paths.triggers(stage, ['.cnb.yml'], SOURCE, shrunk), stage)

    def test_a_push_build_measures_from_its_merge_base_with_main(self):
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)

            def git(*args):
                return ci_paths.run_git('-C', directory, '-c', 'user.name=t', '-c', 'user.email=t@t', *args)
            git('init', '-q', '-b', 'main')
            work.joinpath(ci_paths.CNB_YML).write_text(SOURCE)
            git('add', '-A')
            git('commit', '-q', '-m', 'base')
            fork = git('rev-parse', 'HEAD')
            git('checkout', '-q', '-b', 'owner/x')
            work.joinpath('docs').mkdir()
            work.joinpath('docs/a.md').write_text('a')
            git('add', '-A')
            git('commit', '-q', '-m', 'docs')
            git('checkout', '-q', 'main')
            work.joinpath('lib').mkdir()
            work.joinpath('lib/a.dart').write_text('void main() {}')
            git('add', '-A')
            git('commit', '-q', '-m', 'main moves on')
            git('checkout', '-q', 'owner/x')
            # The repository is its own origin, so the base command's fetch stays on disk.
            git('remote', 'add', 'origin', directory)

            def run(*args):
                return subprocess.run([sys.executable, str(pathlib.Path(ci_paths.__file__).resolve()), *args],
                                      cwd=directory, capture_output=True, text=True)
            # main's own Dart change is not the branch's: the base is the fork point, not main's tip.
            self.assertEqual(fork, run('base').stdout.strip())
            self.assertEqual([ci_paths.SKIP] * 3, [run('trigger', stage, '').returncode for stage in STAGES])
            git('remote', 'remove', 'origin')
            self.assertEqual(ci_paths.EMPTY_TREE, run('base').stdout.strip())
            self.assertEqual([0] * 3, [run('trigger', stage, '').returncode for stage in STAGES])
            self.assertEqual(ci_paths.EMPTY_TREE, git('hash-object', '-t', 'tree', '/dev/null'))

    def test_flutter_stages_use_the_path_rules_and_long_pipelines_try_reuse_first(self):
        def check():
            jobs = {job['name']: job for job in cnb.pipelines()}
            stages = jobs[ci_paths.FLUTTER]['stages'][1:]
            for stage, name in zip(stages, STAGES):
                lines = stage['script'].splitlines()
                self.assertEqual(REUSE, lines[0])
                self.assertEqual(f'python3 .automation/ci_paths.py trigger {name} "$CNB_PULL_REQUEST_TARGET_SHA"'
                                 ' || [ $? -ne 3 ] || exit 0', lines[1])
                self.assertNotIn('grep -Eq', stage['script'])
            for name in ('Go dependency regression tests', 'Rust dependency regression tests'):
                self.assertIn(REUSE, jobs[name]['stages'][0]['script'], name)
        cnb.CnbPipelineTests.both(self, check)

    def test_no_scan_stage_can_reuse_an_earlier_verdict(self):
        def check():
            stages = [stage for job in cnb.pipelines() for stage in job.get('stages', [])]
            scans = [stage for stage in stages if 'scan' in stage.get('name', '').lower()]
            self.assertIn('Rescan actual versions and verify repaired dependency', [s['name'] for s in scans])
            for stage in scans:
                self.assertNotIn('ci_paths.py reuse', stage.get('script', ''), stage['name'])
        cnb.CnbPipelineTests.both(self, check)


    def test_the_stage_script_skips_only_when_no_trigger_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            git = lambda *args: ci_paths.run_git('-C', directory, '-c', 'user.name=t', '-c', 'user.email=t@t', *args)
            git('init', '-q')
            root = pathlib.Path(directory)
            root.joinpath(ci_paths.CNB_YML).write_text(SOURCE)
            git('add', '-A')
            git('commit', '-q', '-m', 'base')
            base = git('rev-parse', 'HEAD')

            def run(stage, revision):
                return subprocess.run([sys.executable, str(pathlib.Path(ci_paths.__file__).resolve()), 'trigger',
                                       stage, revision], cwd=directory, capture_output=True).returncode
            root.joinpath(ci_paths.CNB_YML).write_text(SOURCE.replace('timeout: 10m', 'timeout: 11m'))
            git('commit', '-q', '-am', 'automation timeout')
            self.assertEqual([ci_paths.SKIP] * 3, [run(stage, base) for stage in STAGES])
            root.joinpath('lib').mkdir()
            root.joinpath('lib/a.dart').write_text('void main() {}')
            git('add', '-A')
            git('commit', '-q', '-m', 'dart')
            self.assertEqual(0, run('flutter', base))
            self.assertEqual(0, run('govet', 'f' * 40))

def git_in(directory):
    def git(*args, check=True, env=None):
        return ci_paths.run_git('-C', directory, *args, check=check, env=env)
    return git


class ReuseTests(unittest.TestCase):
    def test_the_whitelist_reuses_only_disjoint_areas_and_neutral_paths(self):
        cases = {(('README.md',), ('lib/a.dart',)): True, (('docs/x.md', 'LICENSE'), ('core/x.go',)): True,
                 (('core/x.go',), ('lib/a.dart', 'test/a_test.dart')): True,
                 (('services/helper/src/main.rs',), ('android/a.kt',)): False,
                 (('android/a.kt',), ('lib/a.dart',)): False, (('lib/a.dart',), ('android/a.kt',)): False,
                 (('lib/a.dart',), ('test/a_test.dart',)): False, (('android/a.kt',), ('core/x.go',)): False,
                 (('pubspec.lock',), ('lib/a.dart',)): False, (('README.md',), ('pubspec.yaml',)): False,
                 (('.cnb.yml',), ('lib/a.dart',)): False, (('lib/a.dart',), ('.automation/wake.py',)): False,
                 (('core/x.go',), ('.cnb/Dockerfile',)): False, (('tool/a.sh',), ('lib/a.dart',)): False,
                 (('plugins/rust_api/x',), ('core/x.go',)): False, ((), ('lib/a.dart',)): False}
        for (main, own), expected in cases.items():
            self.assertEqual(expected, ci_paths.reusable(main, own), (main, own))

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ['rm', '-rf', self.directory])
        self.git = git_in(self.directory)
        self.git('init', '-q', '-b', 'main')
        # CI runners have no global identity, and commit-tree in sync() needs one.
        self.git('config', 'user.name', 't')
        self.git('config', 'user.email', 't@t')
        self.write({'lib/a.dart': 'a', 'core/x.go': 'x', 'pubspec.yaml': 'p', 'README.md': 'r',
                    '.cnb.yml': ci_paths.CNB_YML + ' ' + REUSE})
        self.base = self.commit('base')

    def write(self, files):
        for path, text in files.items():
            target = pathlib.Path(self.directory, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git('add', '-A')

    def commit(self, message, parent=None, files=None):
        if parent:
            self.git('checkout', '-q', '--detach', parent)
        self.write(files or {})
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def sync(self, main_files, own_files, message='Merge main into automation/req-9', extra=None):
        main = self.commit('main', self.base, main_files)
        own = self.commit('own', self.base, own_files)
        tree = self.git('merge-tree', '--write-tree', own, main).split()[0]
        if extra:
            self.git('read-tree', tree)
            self.write(extra)
            tree = self.git('write-tree')
        return own, self.git('commit-tree', tree, '-p', own, '-p', main, '-m', message,
                             '-m', ci_paths.CONTROLLER)

    def test_a_controller_merge_of_disjoint_changes_keeps_the_requirement_verdict(self):
        own, head = self.sync({'README.md': 'docs only'}, {'lib/a.dart': 'b'})
        self.assertEqual(own, ci_paths.reuse_claim(head, self.git, 'automation/req-9'))
        own, head = self.sync({'core/x.go': 'y'}, {'lib/a.dart': 'c'})
        self.assertEqual(own, ci_paths.reuse_claim(head, self.git, 'automation/req-9'))

    def test_shared_inputs_foreign_merges_and_edited_merges_rerun(self):
        for main, own, kwargs, branch in (({'lib/b.dart': 'm'}, {'lib/a.dart': 'b'}, {}, 'automation/req-9'),
                                          ({'pubspec.yaml': 'q'}, {'lib/a.dart': 'b'}, {}, 'automation/req-9'),
                                          ({'.cnb.yml': 'x'}, {'lib/a.dart': 'b'}, {}, 'automation/req-9'),
                                          ({'README.md': 'd'}, {'lib/a.dart': 'b'}, {}, 'automation/req-8'),
                                          ({'README.md': 'd'}, {'lib/a.dart': 'b'}, {}, 'security/group-1'),
                                          ({'README.md': 'd'}, {'lib/a.dart': 'b'},
                                           {'message': "Merge branch 'main'"}, 'automation/req-9'),
                                          ({'README.md': 'd'}, {'lib/a.dart': 'b'},
                                           {'extra': {'core/x.go': 'sneaked in'}}, 'automation/req-9')):
            _, head = self.sync(main, own, **kwargs)
            self.assertEqual('', ci_paths.reuse_claim(head, self.git, branch), (main, kwargs, branch))

    def test_the_stage_script_skips_on_reuse_and_runs_on_any_failure(self):
        own, head = self.sync({'README.md': 'docs only'}, {'lib/a.dart': 'b'})
        self.git('checkout', '-q', '--detach', head)
        script = pathlib.Path(ci_paths.__file__).resolve()

        def run(**env):
            done = subprocess.run([sys.executable, str(script), 'reuse'], cwd=self.directory, text=True,
                                  capture_output=True, env=dict(os.environ, **env))
            return done.returncode, done.stdout
        code, out = run(CNB_PULL_REQUEST_BRANCH='refs/heads/automation/req-9', CNB_PULL_REQUEST_SHA=head)
        self.assertEqual((ci_paths.SKIP, True), (code, own[:12] in out))
        self.assertEqual(0, run(CNB_PULL_REQUEST_BRANCH='automation/req-9', CNB_PULL_REQUEST_SHA=own)[0])
        self.assertEqual(0, run(CNB_PULL_REQUEST_BRANCH='automation/req-9', CNB_PULL_REQUEST_SHA='f' * 40)[0])


if __name__ == '__main__':
    unittest.main()
