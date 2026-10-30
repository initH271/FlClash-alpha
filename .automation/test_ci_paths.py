import pathlib
import subprocess
import sys
import tempfile
import unittest

import ci_paths
import test_cnb_pipelines as cnb

SOURCE = cnb.CNB.read_text(encoding='utf-8')
STAGES = ('flutter', 'android', 'govet')


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
        renamed = SOURCE.replace(f'- name: {ci_paths.FLUTTER}', '- name: Flutter tests')
        aliased = SOURCE.replace('      runner: { cpus: 4 }\n      docker:\n        image: ubuntu:24.04',
                                 '      runner: *big\n      docker:\n        image: ubuntu:24.04')
        outside = SOURCE.replace("echo 'Skipped: no automation changes'", "echo 'Skipped'")
        self.assertNotEqual(SOURCE, aliased)
        for old, new in ((renamed, renamed.replace("echo 'Skipped: no automation changes'", "echo 'x'")),
                         (aliased, aliased.replace("echo 'Skipped: no automation changes'", "echo 'x'")),
                         ('', outside)):
            self.assertTrue(ci_paths.triggers('flutter', ['.cnb.yml'], old, new))

    def test_flutter_stages_use_the_path_rules(self):
        def check():
            jobs = {job['name']: job for job in cnb.pipelines()}
            stages = jobs[ci_paths.FLUTTER]['stages'][1:]
            for stage, name in zip(stages, STAGES):
                self.assertEqual(f'python3 .automation/ci_paths.py trigger {name} "$CNB_PULL_REQUEST_TARGET_SHA"'
                                 ' || [ $? -ne 3 ] || exit 0', stage['script'].splitlines()[0])
                self.assertNotIn('grep -Eq', stage['script'])
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

if __name__ == '__main__':
    unittest.main()
