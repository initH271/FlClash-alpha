import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD = "always() && steps.credentials.outcome == 'success'"
GUARDED_STEPS = (
    'Notify new stable upstream release',
    'Bring CNB main up to GitHub main',
    'Process owner approvals',
    'Reuse artifacts of stopped release builds',
)


def step_conditions():
    """Map each controller step name to its if: text, read as plain text so it works without yaml."""
    source = (ROOT / '.github/workflows/upstream.yaml').read_text(encoding='utf-8')
    found = {}
    for block in re.split(r'\n      - ', source)[1:]:
        name = re.search(r'name: (.+)', block)
        cond = re.search(r'\n        if: (.+)', block)
        if name:
            found[name.group(1).strip()] = cond.group(1).strip() if cond else None
    return found


FORBIDDEN = ('/merge', "'PATCH'", "'PUT'", 'promote(')


GONE = {'ci_paths', 'fallback', 'npc_recovery', 'pause', 'release_permission_probe', 'requirements', 'review_evidence',
        'reviews', 'security_finish', 'security_groups', 'security_queue', 'security_watch', 'wake'}


def defined(tree):
    """The names a module binds at its top level, its own imports included."""
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(alias.asname or alias.name).split('.')[0] for alias in node.names}
    return names


def reachable_source(module, entry):
    """Source text of entry and every same-module function it reaches by plain calls."""
    path = ROOT / '.automation' / f'{module}.py'
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    seen, todo = set(), [entry]
    while todo:
        name = todo.pop()
        if name in seen or name not in funcs:
            continue
        seen.add(name)
        for node in ast.walk(funcs[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                todo.append(node.func.id)
    return '\n'.join(ast.get_source_segment(text, funcs[n]) for n in sorted(seen))


class WorkflowGateTests(unittest.TestCase):
    def test_independent_steps_still_run_after_an_earlier_failure(self):
        conditions = step_conditions()
        for name in GUARDED_STEPS:
            with self.subTest(step=name):
                self.assertIn(name, conditions)
                self.assertTrue(conditions[name].startswith(GUARD + ' && '), conditions[name])

    def test_original_conditions_stay_parenthesised_where_they_use_or(self):
        for name, cond in step_conditions().items():
            if cond and cond.startswith(GUARD) and '||' in cond:
                with self.subTest(step=name):
                    self.assertTrue(cond.startswith(GUARD + ' && (') and cond.endswith(')'), cond)

    def test_job_failure_is_not_masked(self):
        source = (ROOT / '.github/workflows/upstream.yaml').read_text(encoding='utf-8')
        self.assertNotIn('continue-on-error', source)

    def test_the_controller_steps_are_gone(self):
        source = (ROOT / '.github/workflows/upstream.yaml').read_text(encoding='utf-8')
        for script in ('reviews.py', 'npc_recovery.py', 'security_queue.py', 'security_finish.py', 'requirements.py',
                       'FLCLASH_SECURITY_OUTCOME'):
            self.assertNotIn(script, source)
        self.assertFalse((ROOT / '.github/workflows/reviews.yaml').exists())

    def test_every_scheduled_run_brings_cnb_main_up_to_date(self):
        # A merge without a new version skips build.yaml's sync, so this is what carries it, and .cnb.yml, to CNB.
        block = next(b for b in re.split(r'\n      - ', (ROOT / '.github/workflows/upstream.yaml').read_text(encoding='utf-8'))
                     if 'Bring CNB main up to GitHub main' in b)
        self.assertIn('python3 .automation/control.py sync', block)
        self.assertEqual(GUARD + " && inputs.operation != 'preflight'", step_conditions()['Bring CNB main up to GitHub main'])

    def test_the_upstream_workflow_keeps_its_own_schedules(self):
        # Nothing wakes it from CNB any more: watch runs every six hours, approvals and the scheduler hourly.
        source = (ROOT / '.github/workflows/upstream.yaml').read_text(encoding='utf-8')
        self.assertEqual(["17 */6 * * *", "0 * * * *"], re.findall(r"cron: '([^']+)'", source))

    def test_the_release_build_publishes_from_main_without_a_fallback(self):
        source = (ROOT / '.github/workflows/build.yaml').read_text(encoding='utf-8')
        for gone in ('cnb_fallback', 'CNB_FALLBACK', 'fallback.py'):
            self.assertNotIn(gone, source)
        for step in ('python3 .automation/build_plan.py', 'python3 .automation/reuse.py',
                     'bash .github/scripts/sign-apk.sh', 'python3 .automation/control.py promote',
                     'python3 .automation/control.py validate', 'python3 .automation/control.py notify',
                     'python3 .automation/control.py status'):
            self.assertIn(step, source)
        self.assertLess(source.index('control.py promote'), source.index('gh release create'))
        self.assertLess(source.index('gh release create'), source.index('control.py notify'))

    def test_every_script_a_pipeline_runs_exists(self):
        sources = [*(ROOT / '.github/workflows').glob('*.y*ml'), ROOT / '.cnb.yml']
        scripts = set()
        for path in sources:
            scripts |= set(re.findall(r'(?:tools/)?(\.(?:automation|cnb|github)/[\w./-]+\.(?:py|sh))',
                                      path.read_text(encoding='utf-8')))
        self.assertIn('.automation/control.py', scripts)
        for script in scripts:
            with self.subTest(script=script):
                self.assertTrue((ROOT / script).is_file())

    def test_every_control_command_a_pipeline_runs_exists(self):
        sources = ''.join(path.read_text(encoding='utf-8') for path in (ROOT / '.github/workflows').glob('*.y*ml'))
        tree = ast.parse((ROOT / '.automation/control.py').read_text(encoding='utf-8'))
        commands = next(ast.literal_eval(ast.Tuple(node.value.keys, ast.Load())) for node in ast.walk(tree)
                        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'commands')
        used = set(re.findall(r'\.automation/control\.py (\w+)', sources))
        self.assertTrue(used)
        self.assertLessEqual(used, set(commands))

    def test_the_release_build_can_reach_the_github_issues_it_tidies(self):
        source = (ROOT / '.github/workflows/build.yaml').read_text(encoding='utf-8')
        self.assertEqual(['contents: write', 'actions: read', 'statuses: write', 'issues: write'],
                         re.findall(r'^  (\w[\w-]*: \w+)$', source.split('permissions:\n')[1].split('concurrency:')[0], re.M))
        self.assertIn('issues: write', (ROOT / '.github/workflows/upstream.yaml').read_text(encoding='utf-8'))

    def test_the_approval_workflow_runs_mains_code_for_the_owner_only(self):
        source = (ROOT / '.github/workflows/upstream-approval.yml').read_text(encoding='utf-8')
        self.assertEqual(['issue_comment'], re.findall(r'^  ([\w-]+):$', source.split('permissions:')[0].split('on:')[1], re.M))
        self.assertIn('types: [created]', source)
        self.assertNotIn('pull_request_target', source)
        condition = re.search(r'^    if: (.+)$', source, re.M).group(1)
        for part in ('github.event.issue.pull_request == null', 'github.event.comment.user.login == github.repository_owner',
                     "github.event.issue.user.login == 'github-actions[bot]'"):
            self.assertIn(part, condition)
        self.assertIn('ref: main', source)
        self.assertLess(source.index('unittest discover'), source.index('control.py approvals'))
        self.assertEqual(['contents: write', 'pull-requests: write', 'issues: write'],
                         re.findall(r'^  (\w[\w-]*: \w+)$', source.split('permissions:\n')[1].split('jobs:')[0], re.M))

    def test_no_comment_or_title_text_reaches_a_shell_or_the_environment(self):
        for name in ('upstream-approval.yml', 'npc-upstream.yml', 'upstream.yaml'):
            source = (ROOT / '.github/workflows' / name).read_text(encoding='utf-8')
            self.assertFalse(re.search(r'\$\{\{[^}]*(comment\.body|issue\.body|issue\.title|\.title|\.body)', source), name)
            for block in re.findall(r'run: (\|\n(?:\s+.*\n)+|.*)', source):
                self.assertNotIn('${{', block, name)
        approval = (ROOT / '.github/workflows/upstream-approval.yml').read_text(encoding='utf-8')
        self.assertEqual(['github.token', 'github.event.issue.number'],
                         re.findall(r'\$\{\{ ([^}]+) \}\}', approval))

    def test_the_approval_queue_is_entered_only_by_a_job_that_will_run(self):
        # A skipped job from a stranger's comment must not push a real approval out of the one pending slot.
        source = (ROOT / '.github/workflows/upstream-approval.yml').read_text(encoding='utf-8')
        self.assertNotRegex(source, r'(?m)^concurrency:')
        self.assertIn('    concurrency:\n      group: flclash-upstream-controller', source)

    def test_the_analysis_workflow_is_advice_and_uses_only_what_it_must(self):
        source = (ROOT / '.github/workflows/npc-upstream.yml').read_text(encoding='utf-8')
        steps = re.split(r'^      - ', source.split('steps:\n')[1], flags=re.M)[1:]
        self.assertEqual(3, len(steps))
        for step in steps:
            self.assertIn('continue-on-error: true', step)
        self.assertIn('permissions:\n  contents: read\n  issues: write\nconcurrency:', source)
        self.assertIn('persist-credentials: false', source)
        self.assertIn('if: cancelled()', source)
        self.assertIn('python3 .github/scripts/npc_review.py upstream', source)

    def test_the_owner_ok_also_has_the_hourly_pass_behind_it(self):
        self.assertIn('python3 .automation/control.py approvals', (ROOT / '.github/workflows/upstream.yaml').read_text(encoding='utf-8'))
        self.assertIn("github.event.schedule == '0 * * * *'", step_conditions()['Process owner approvals'])

    def test_no_automation_module_imports_a_name_that_is_gone(self):
        directory = ROOT / '.automation'
        modules = {path.stem: ast.parse(path.read_text(encoding='utf-8')) for path in directory.glob('*.py')}
        for name, tree in modules.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    pairs = [(alias.name, None) for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    pairs = [(node.module, alias.name) for alias in node.names]
                else:
                    continue
                for module, symbol in pairs:
                    self.assertNotIn(module, GONE, f'{name} imports {module}')
                    if module in modules and symbol:
                        self.assertIn(symbol, defined(modules[module]), f'{name} imports {module}.{symbol}')

    def test_always_run_steps_never_merge_or_push_main_themselves(self):
        """Running after a failed security step must only record approvals and schedule builds.

        Publishing lives in build.yaml, on the current main; the two always-run entry points must not reach it.
        """
        for module, entry in (('control', 'approvals'), ('scheduler', 'schedule')):
            source = reachable_source(module, entry)
            for token in FORBIDDEN:
                with self.subTest(entry=entry, token=token):
                    self.assertNotIn(token, source)


if __name__ == '__main__':
    unittest.main()
