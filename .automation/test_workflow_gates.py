import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD = "always() && steps.credentials.outcome == 'success'"
GUARDED_STEPS = (
    'Notify new stable upstream release',
    'Reconcile PR review gates',
    'Process owner approvals',
    'Reuse artifacts or dispatch infrastructure fallback',
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


FORBIDDEN = ('/merge', "'PATCH'", "'PUT'", 'promote(', 'merge_one(')


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

    def test_build_dispatching_steps_receive_the_security_finish_outcome(self):
        source = (ROOT / '.github/workflows/upstream.yaml').read_text(encoding='utf-8')
        blocks = {re.search(r'name: (.+)', b).group(1).strip(): b
                  for b in re.split(r'\n      - ', source)[1:] if re.search(r'name: (.+)', b)}
        step_id = re.search(r'\n        id: (\S+)', blocks['Finish verified compatible security repairs'])
        self.assertIsNotNone(step_id)
        expected = 'FLCLASH_SECURITY_OUTCOME: ${{ steps.%s.outcome }}' % step_id.group(1)
        for name in ('Process owner approvals', 'Reuse artifacts or dispatch infrastructure fallback'):
            with self.subTest(step=name):
                self.assertRegex(blocks[name], r'\n        env:\n(          .+\n)*          '
                                 + re.escape(expected) + r'\n')

    def test_security_finish_runs_whenever_a_build_dispatching_step_runs(self):
        """control.security_hold lets a skipped security outcome through.

        That is only safe while every run of approvals or the scheduler also runs the security step.
        Each alternative inside their parentheses must be a schedule event, which carries no inputs, or
        an explicit non-preflight operation; anything else could let a skipped security step release a build.
        """
        conditions = step_conditions()
        security = conditions['Finish verified compatible security repairs']
        self.assertEqual(security, GUARD + " && inputs.operation != 'preflight'",
                         'security finish condition changed: re-check that skipped still implies it never ran '
                         'alongside approvals or the scheduler, then update this test')
        for name in ('Process owner approvals', 'Reuse artifacts or dispatch infrastructure fallback'):
            cond = conditions[name]
            with self.subTest(step=name):
                self.assertTrue(cond.startswith(GUARD + ' && (') and cond.endswith(')'), cond)
                for option in cond[len(GUARD + ' && ('):-1].split(' || '):
                    schedule = re.fullmatch(r"github\.event\.schedule == '[^']+'", option)
                    operation = re.fullmatch(r"inputs\.operation == '([a-z_]+)'", option)
                    self.assertTrue(schedule or (operation and operation.group(1) != 'preflight'),
                                    f'{name} may run without the security step on {option!r}; a skipped '
                                    'security outcome would then release a build unchecked')

    def test_always_run_steps_never_merge_or_push_main_themselves(self):
        """Running after a failed security step must only record approvals and schedule builds.

        Merging and publishing live in security_finish.py and in build.yaml's promote step,
        which re-validates the candidate; the two always-run entry points must not reach them.
        """
        for module, entry in (('control', 'approvals'), ('scheduler', 'schedule')):
            source = reachable_source(module, entry)
            for token in FORBIDDEN:
                with self.subTest(entry=entry, token=token):
                    self.assertNotIn(token, source)


if __name__ == '__main__':
    unittest.main()
