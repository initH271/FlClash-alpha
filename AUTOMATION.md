# FlClash-alpha automation

GitHub is the single source of truth: issues, pull requests, CI, signing and releases. CNB serves downloads inside China
and supplies NPC compute. Merging takes CI and the owner's click. A model's output is only ever advice.

## Pull requests

1. Develop locally with Claude, or by hand. Claude runs only on the owner's machine: there is no Claude Action, App or
   token on GitHub.
2. Push the branch to GitHub and open a PR.
3. Wait for the required checks: `ci-ok` and `Dependency vulnerability scan`.
4. Read the NPC comment, if there is one.
5. The owner merges.

Branch protection on `main` requires those two checks and an up-to-date branch, and applies to admins. It requires no
review. A user-visible UI change needs before and after screenshots and the owner's confirmation before merging. That
rule is in the PR template, and no check enforces it.

| Check | Workflow | What it does |
|---|---|---|
| `ci-ok` | `.github/workflows/ci.yml` | Runs on every PR and passes when every job passed or was skipped. `.github/scripts/ci_changes.py` picks the jobs from the changed paths: automation tests, Go, Rust, Flutter, Android unit tests, Android release compile. A path no rule names runs every job. A change to `.automation/policy.json` runs every job |
| `Dependency vulnerability scan` | `.github/workflows/security.yaml` | See [SECURITY_AUTOMATION.md](SECURITY_AUTOMATION.md) |
| `NPC review (advisory)` | `.github/workflows/npc-review.yml` | Not required, and not part of `ci-ok` |

### NPC review

`npc-review.yml` starts the CNB event `api_trigger_npc_review`, reads the report from the build log and writes one PR
comment, updated on each head. It skips drafts, forks and Dependabot PRs. Every failure path leaves the PR green and just
means no comment, including a large diff that uses up the 40 turns. Merge without it when it is missing.

## Releases

Change `.github/release.json` and `.github/release-notes.md` in a PR. Merging that PR releases.

Every push to `main` runs `.github/workflows/build.yaml`. `.automation/build_plan.py` takes the tag from `release.json`.
If that tag is already published, the run stops there, so a merge without a version change publishes nothing. Otherwise
the run tests, compiles, signs and verifies the APK, moves CNB main with `control.py promote`, publishes the GitHub
Release, and `control.py notify` starts the CNB mirror.

Only the current `main` builds. If a later step fails after the APK was built, `.automation/scheduler.py` reruns the build
with that artifact on its hourly pass, without compiling again. A branch `automation/recovery-<run>` marks that attempt, so
keep those branches. A failure it cannot reuse opens a `[构建待处理]` Issue, and a later release that contains the commit
closes it.

`control.py status` also writes the commit status `FlClash/approved-build`. Nothing reads it.

[RELEASE_CHANNELS.md](RELEASE_CHANNELS.md) covers the channels and the app's updater, and
[CHANGELOG_STYLE.md](CHANGELOG_STYLE.md) covers the release text.

## Upstream upgrades

Not yet run end to end. See [Not yet exercised](#not-yet-exercised).

1. `.github/workflows/upstream.yaml` checks the latest stable upstream release every six hours and ignores versions at or
   below `upstream_tag` in `.automation/policy.json`. Each new version opens one Issue assigned to the owner, with the
   upstream commit in a marker. The release text is linked, not copied, so its mentions notify nobody. A closed Issue is
   not recreated.
2. `.github/workflows/npc-upstream.yml` posts one read-only NPC analysis on the Issue. It is advice, and a failure leaves
   no comment. Run the workflow by hand on `main` to retry.
3. The owner comments exactly `OK` or `OK vX.Y.Z`. Comments from anyone else, and Issues the bot did not open, do not
   count. `.github/workflows/upstream-approval.yml` reacts within about a minute, and the hourly pass of `upstream.yaml`
   covers a lost event. Closing the Issue withdraws the upgrade.
4. A clean merge goes on `agent/upstream-vX.Y.Z` with the new `upstream_tag` and `upstream_sha`, and opens a PR that closes
   the Issue when merged. To start over after closing that PR unmerged, delete the branch.
5. `GITHUB_TOKEN` opened that PR, so its workflows wait for approval. Select **Approve workflows to run** in the merge box,
   or close and reopen the PR. A `workflow_dispatch` run does not help, because GitHub does not count its checks towards a
   required check.
6. The owner merges. This publishes nothing: release in a later PR, as in [Releases](#releases).

### Conflicting upstream upgrades

When the approved upstream commit conflicts with `main`, or touches a path in `protected_paths` of
`.automation/policy.json`, nothing is merged or pushed. The Issue gets one comment listing the files and the upstream
commit, and it is not retried. The owner then:

1. Merges that upstream commit on a branch of their own, resolving the conflicts by [FORK_PATCHES.md](FORK_PATCHES.md).
2. Sets `upstream_tag` and `upstream_sha` in `.automation/policy.json` to that version.
3. Opens a PR whose body says `Closes #<Issue>`. Its CI starts by itself, since the owner opened it.

## Dependencies

Dependabot and the scan, with what each one misses: [SECURITY_AUTOMATION.md](SECURITY_AUTOMATION.md).

## CNB

`.cnb.yml` does these things, and CNB runs no CI:

- **Download mirror**: `.cnb/mirror-release.py` on a push to CNB main, hourly at minute 7, and when `control.py notify` or
  the web button starts it. See [RELEASE_CHANNELS.md](RELEASE_CHANNELS.md).
- **NPC compute**: `api_trigger_npc_review` and `api_trigger_npc_upstream`. Both run `deepseek-v4.1-flash` with
  `sandbox: true` and 40 turns. GitHub starts them with `npc: {name: CodeBuddy}`, which counts against development quota.
  The prompts live in `.cnb.yml`, and each request carries only validated numbers and SHAs. Keep secrets out of them,
  since the configuration and results are publicly readable.
- **Cloud development**: see [CNB_DEVELOPMENT.md](CNB_DEVELOPMENT.md).

CNB main follows GitHub main one way. Every run of `upstream.yaml` runs `control.py sync`, so a merge reaches CNB within
about an hour, and a release moves it immediately. The step fails if CNB main has commits GitHub does not have, and it
leaves both branches alone. A new `.cnb.yml` takes effect only once it reaches CNB main.

Automation writes no CNB Issues or comments, and nothing on CNB merges. Bug reports go to GitHub Issues.

## Notifications

| Source | What you get | When |
|---|---|---|
| `control.watch` | Issue assigned to the owner | New stable upstream version, one per version |
| `npc-upstream.yml` | Issue comment | After `watch` |
| `control.open_pull_request` | PR, and an Issue comment with the link | After OK |
| `control.report_conflict` | Issue comment | After OK, on a conflict or protected path, once per upstream commit |
| `scheduler.notify_once` | `[构建待处理]` Issue assigned to the owner | Build on `main` failed and cannot be reused, one per run |
| `npc-review.yml` | PR comment | Each head of a non-Dependabot PR |
| Dependabot | PRs, alert emails | Weekly, or when an advisory appears |
| GitHub | Workflow failure email | Scheduled or release run failed |

## Credentials

GitHub Actions secrets, and these two are all there are:

| Secret | Used by | Needs |
|---|---|---|
| `ANDROID_DEBUG_KEYSTORE` | `build.yaml`, `sign-existing.yaml` | The personal signing key. It stays on GitHub only |
| `CNB_AUTOMATION_TOKEN` | `build.yaml`, `upstream.yaml`, `npc-review.yml`, `npc-upstream.yml` | On `507space/FlClash-alpha`: code push, build trigger, status, stop and stage logs, release read |

The CNB mirror uses CNB's own pipeline token. Everything else on GitHub uses `GITHUB_TOKEN`, with permissions declared in
each workflow. The repository default is read-only, and Actions may create pull requests.

## Manual controls

Run these from GitHub Actions on `main`:

- `upstream.yaml`, `operation`: `watch`, `sync`, `approvals`, `scheduler`, `preflight` (checks the CNB token), `all`.
- `build.yaml`: `source_ref` must be the current `main`. `reuse_run` takes a run whose artifact to reuse.
- `npc-upstream.yml`: `issue`, `tag`, `base`, `head`.
- `sign-existing.yaml`: signs the artifact of an earlier run.

## Changing the process

A change to `.github/`, `.automation/`, `.cnb/` or `.cnb.yml` is an ordinary PR, with the same checks and the owner's merge.

- Update this file or `SECURITY_AUTOMATION.md` in the same PR, and rewrite whatever went stale rather than adding to it.
- Run the checks first:

  ```bash
  python3 -m unittest discover -s .automation -p 'test_*.py'
  python3 .cnb/test_mirror_release.py
  python3 -m unittest tool.test_release_identity
  uvx --from actionlint-py actionlint .github/workflows/*.y*ml
  ```

- `npc-review.yml` runs `.github/scripts/npc_review.py` from the base commit, and the scan runs its scanner from `main`, so
  a PR that changes either does not exercise its own change.
- `upstream.yaml` and `upstream-approval.yml` run the `.automation` tests on `main` before they change anything, so a red
  test on `main` stops upstream handling.

## Not yet exercised

Unit tests and read-only dry runs cover these. None has run for real:

- The upstream path from OK onwards: the `issue_comment` trigger, the bot's push and PR, `Closes #<Issue>`.
- The checks of a bot PR, after **Approve workflows to run**, satisfying the required checks.
- `api_trigger_npc_upstream`, including whether a truncated diff of about 1 MB still yields a useful analysis.
- A real release since this process replaced the old one: `control.py promote`, `notify`, and the mirror it starts.
- Dependabot security updates on `/core`, and the Cargo patch-only rule.
