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
| `Windows build`, `Windows helper test` | `.github/workflows/windows.yaml` | Not required, and not part of `ci-ok`. Runs when a PR changes `windows/`, `services/helper/`, `plugins/`, `core/`, `setup.dart`, `pubspec.yaml`, `pubspec.lock`, `build_config.yaml`, `distribute_options.yaml`, `.gitmodules`, the workflow or its script. It leaves `lib/` to analyze and test on Linux, since the Windows risk sits in native code and build scripts. The packages stay on the run as an artifact for 3 days |

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

`.github/workflows/windows.yaml` then adds the Windows files, in a run of its own that `build.yaml` and
`.automation/scheduler.py` never look at, so a Windows failure cannot turn the Android release red. See
[Windows packages](#windows-packages).

Only the current `main` builds. If a later step fails after the APK was built, `.automation/scheduler.py` reruns the build
with that artifact on its hourly pass, without compiling again. A branch `automation/recovery-<run>` marks that attempt, so
keep those branches. A failure it cannot reuse opens a `[构建待处理]` Issue, and a later release that contains the commit
closes it.

`control.py status` also writes the commit status `FlClash/approved-build`. Nothing reads it.

### Windows packages

`windows.yaml` starts when `Android release` completes. `.automation/windows_release.py plan` ends the run green, without
compiling, unless that run succeeded on this repository's `main` from a `push` or `workflow_dispatch`, the `release.json`
of its commit names a published Release whose target is that same commit, and the Release lacks a Windows file. So a merge
without a version change builds nothing, and adding packages to an older Release takes a manual retry.

`Windows build` compiles on `windows-2022` with no secret and a read-only token. `.automation/windows_release.py stamp`
writes the release identity into `pubspec.yaml` on the runner, because `flutter_distributor` and the Windows runner read
the version only from there, and `package` fails the build if `FlClash.exe` or the installer carries another version or
the archive lacks a file the app needs. It also fetches the CA bundle upstream pins, which the core embeds and the
submodule keeps empty; bump `CA_BUNDLE` and `CA_BUNDLE_SHA256` with upstream.

`Windows publish` checks the artifact again, uploads `FlClash-alpha-windows-amd64-setup.exe` and
`FlClash-alpha-windows-amd64.zip`, and only then replaces `SHA256SUMS.txt` with the APK line first and unchanged and the
two Windows lines after it. Title, body, `update.json` and the latest flag stay as they were. Then `control.py mirror`
starts the CNB mirror; if that start fails, the hourly mirror run picks the files up.

A failed publish run opens the Issue `[Windows 构建待处理] <tag>`, assigned to the owner, with the way to retry: run
`windows.yaml` on `main` with `release_tag`. A later success closes it. A Release that already has both files is left
alone, so its bytes do not change after the mirror copied them.

Measured on `windows-2022` for a PR: `Windows build` 11 to 14 minutes, of which the Flutter build is about 8, and `Windows
helper test` about 1 minute. The installer is about 44 MB and the archive about 69 MB. A release spends the same on
`Windows build`, on top of the Android run it follows.

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

- **Download mirror**: `.cnb/mirror-release.py` on a push to CNB main, hourly at minute 7, and when `control.py notify`,
  `control.py mirror` or the web button starts it. See [RELEASE_CHANNELS.md](RELEASE_CHANNELS.md).
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
| `windows_release.report` | `[Windows 构建待处理]` Issue assigned to the owner | Windows build or upload of a release failed, one per tag, later runs comment on it |
| `npc-review.yml` | PR comment | Each head of a non-Dependabot PR |
| Dependabot | PRs, alert emails | Weekly, or when an advisory appears |
| GitHub | Workflow failure email | Scheduled or release run failed |

## Credentials

GitHub Actions secrets, and these two are all there are:

| Secret | Used by | Needs |
|---|---|---|
| `ANDROID_DEBUG_KEYSTORE` | `build.yaml`, `sign-existing.yaml` | The personal signing key. It stays on GitHub only |
| `CNB_AUTOMATION_TOKEN` | `build.yaml`, `windows.yaml` (the one step that starts the mirror), `upstream.yaml`, `npc-review.yml`, `npc-upstream.yml` | On `507space/FlClash-alpha`: code push, build trigger, status, stop and stage logs, release read |

The CNB mirror uses CNB's own pipeline token. Everything else on GitHub uses `GITHUB_TOKEN`, with permissions declared in
each workflow. The repository default is read-only, and Actions may create pull requests.

## Manual controls

Run these from GitHub Actions on `main`:

- `upstream.yaml`, `operation`: `watch`, `sync`, `approvals`, `scheduler`, `preflight` (checks the CNB token), `all`.
- `build.yaml`: `source_ref` must be the current `main`. `reuse_run` takes a run whose artifact to reuse.
- `npc-upstream.yml`: `issue`, `tag`, `base`, `head`.
- `sign-existing.yaml`: signs the artifact of an earlier run.
- `windows.yaml`: `release_tag` empty compiles the selected ref and keeps the packages on the run. `release_tag` set, on
  `main`, builds that Release's target commit and adds the Windows files, unless it already has both.

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
- `windows.yaml` beyond the PR compile: the `workflow_run` trigger, `release_tag`, `Windows publish`, the failure Issue,
  and whether a recovery run of `build.yaml`, which `GITHUB_TOKEN` dispatches, fires `workflow_run` at all. If it does
  not, run `windows.yaml` with `release_tag`.
- The mirror adding files to a Release already published on CNB, and comparing the `size` CNB reports. The OpenAPI
  schema documents `assets`, `size` and `overwrite`, and sets no such restriction, but no run has done it.
- Installing or starting any Windows package: CI only compiles and inspects them.
