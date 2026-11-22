# FlClash-alpha automation

GitHub is the single source of truth: issues, pull requests, CI, signing and releases. Merging takes CI and the owner's
click.

## Pull requests

1. Develop locally with Claude, or by hand. Claude runs only on the owner's machine: there is no Claude Action, App or
   token on GitHub.
2. Push the branch to GitHub and open a PR.
3. Wait for the required checks: `ci-ok` and `Dependency vulnerability scan`.
4. The owner merges.

Branch protection on `main` requires those two checks and an up-to-date branch, and applies to admins. It requires no
review. A user-visible UI change needs before and after screenshots and the owner's confirmation before merging. That
rule is in the PR template, and no check enforces it.

| Check | Workflow | What it does |
|---|---|---|
| `ci-ok` | `.github/workflows/ci.yml` | Runs on every PR and passes when every job passed or was skipped. `.github/scripts/ci_changes.py` picks the jobs from the changed paths: automation tests, Go, Rust, Flutter, plugin tests, Android unit tests, Android release compile. A path no rule names runs every job. A change to `ci.yml` or `.automation/policy.json` runs every job. Documents and templates (`docs/`, `.agents/`, root `*.md` except `AUTOMATION.md`, the PR and Issue templates) run none. `AUTOMATION.md` runs only the automation tests, because one of them reads it. Other workflows, `.github/scripts/`, `.github/dependabot.yml` and `macos/` run only the automation tests. `linux/`, `windows/` and `.github/release-notes.md` also run the Flutter job, and so do `core/Clash.Meta`, `core/protocol.go`, `core/service_check.go`, `services/helper/src/service/peer.rs` and `services/helper/src/service/windows.rs` on top of their own jobs, because Dart tests read them. No job compiles a desktop platform |
| `Dependency vulnerability scan` | `.github/workflows/security.yaml` | See [SECURITY_AUTOMATION.md](SECURITY_AUTOMATION.md) |
| `Windows build`, `Windows helper test` | `.github/workflows/windows.yaml` | Not required, and not part of `ci-ok`. Runs when a PR changes `windows/`, `services/helper/`, `plugins/`, `core/`, `tool/package.dart`, `tool/src/package/`, `pubspec.yaml`, `pubspec.lock`, `build_config.yaml`, `.gitmodules`, the workflow, its scripts or `lib/common/app_update.dart`. It leaves `lib/` to analyze and test on Linux, since the Windows risk sits in native code and build scripts. The packages stay on the run as an artifact for 3 days |

### Plugin tests

The `plugins` job runs the Dart tests under `plugins/*/test` and `plugins/setup/setup_hooks/test`. Root `flutter test` does
not reach them. It runs in parallel with the other jobs, and only for the paths that run every job, such as `plugins/`, the
root `pubspec.yaml` and `pubspec.lock`, `tool/` and `ci.yml`. `lib/`, `test/`, `core/`, `android/` and `services/` do not start
it, since these tests read only files inside `plugins/`. Some read the macOS and Windows sources as text and hold on
any runner, so this job checks that native code on Linux without compiling it.

Each package runs from its own directory, so the job needs no submodule, Rust or Go, and no build hook runs. Only
`setup_hooks` has a committed lockfile, which the job enforces. The others ignore theirs and resolve from their pubspecs on
each run, so a new release of a direct dependency can turn the job red with no change in the PR.

### Go cache

Jobs that share a Go version and `core/go.sum` share one cache key, and the key cannot be overwritten, so the first save
decides what everyone restores. PR saves stay with that PR. On `main` only a release compile in `build.yaml` saves it, and
`security.yaml` sets `cache: false` because its scan compiles nothing. Until a release has saved the current key, each
PR's first run misses and that PR saves its own copy. To replace a bad entry, delete it after the change that stopped it
reaches `main`, and let the next release write it: a manual `ci.yml` run on `main` saves whichever job ends first.

## Releases

Change `.github/release.json` and `.github/release-notes.md` in a PR. Merging that PR releases.

Every push to `main` runs `.github/workflows/build.yaml`. `.automation/build_plan.py` takes the tag from `release.json`.
If that tag is already published, the run stops there, so a merge without a version change publishes nothing. Otherwise
the run tests, compiles, signs and verifies the APK and publishes the GitHub Release, and `control.py notify` closes the
`[构建待处理]` Issues that the release resolves.

`.github/workflows/windows.yaml` then adds the Windows files, in a run of its own that `build.yaml` and
`.automation/scheduler.py` never look at, so a Windows failure cannot turn the Android release red. See
[Windows packages](#windows-packages).

Only the current `main` builds. If a later step fails after the APK was built, `.automation/scheduler.py` reruns the build
with that artifact on its hourly pass, without compiling again. A branch `automation/recovery-<run>` marks that attempt, so
keep those branches. A failure it cannot reuse opens a `[构建待处理]` Issue, which `control.py notify` closes once a later
release contains the commit.

`control.py status` also writes the commit status `FlClash/approved-build`. Nothing reads it.

### Windows packages

`windows.yaml` starts when `Android release` completes. `.automation/windows_release.py plan` ends the run green, without
compiling, unless that run succeeded on this repository's `main` from a `push` or `workflow_dispatch`, the `release.json`
of its commit names a published Release whose target is that same commit, and the Release lacks a Windows file or the
signed manifest. So a merge
without a version change builds nothing, and adding packages to an older Release takes a manual retry.

`Windows build` compiles on `windows-2022` with no secret and a read-only token. `.automation/windows_release.py stamp`
writes the release identity into `pubspec.yaml` on the runner, because `tool/package.dart` and the Windows runner read
the version only from there, and `package` fails the build if `FlClash.exe` or the installer carries another version or
the archive lacks a file the app needs. It also fetches the CA bundle upstream pins, which the core embeds and the
submodule keeps empty; bump `CA_BUNDLE` and `CA_BUNDLE_SHA256` with upstream.

Before keeping the packages, `.automation/windows_smoke.ps1` installs the installer on the runner, and any failure fails
the build, so a publish run then publishes nothing. It installs with the arguments the in-app updater uses, checks the
directory, the uninstall entry under the app's GUID and the publisher, waits for the relaunched app and keeps it up for 20
seconds, registers the helper service under its own name, asks it for `/logs` on the port it published and stops it,
installs again over the running app, and uninstalls silently until the directory and the entry are gone.

`Windows publish` checks the artifact again and copies the release fields of `update.json` into a new signed
`update-windows.json` (see [RELEASE_CHANNELS.md](RELEASE_CHANNELS.md#app-updates)). Only that one step receives
`ANDROID_DEBUG_KEYSTORE`: `keytool` and `openssl` turn it into a temporary PEM that is gone when signing ends, and the run
fails before any upload unless the signature verifies with the certificate in `lib/common/app_update.dart` and that
certificate matches the APK's. The uploads then go in this order: `FlClash-alpha-windows-amd64-setup.exe` and
`FlClash-alpha-windows-amd64.zip`, `SHA256SUMS.txt` with the APK line first and unchanged and the three Windows lines
after it, and `update-windows.json` last: the app downloads as soon as it reads the manifest, and its presence is what
marks the publish complete. Title, body, `update.json` and the latest flag stay as they were.

A failed publish run opens the Issue `[Windows 构建待处理] <tag>`, assigned to the owner, with the way to retry: run
`windows.yaml` on `main` with `release_tag`. A later success closes it. A Release that already has all three files is left
alone, so the bytes an installed app may already have read do not change.

Measured on `windows-2022` for a PR: `Windows build` 8 minutes with warm caches and up to 14 without, and `Windows helper
test` about 1 minute. The installer is about 44 MB and the archive about 69 MB. A release spends the same on
`Windows build`, on top of the Android run it follows.

[RELEASE_CHANNELS.md](RELEASE_CHANNELS.md) covers the channels and the app's updater, and
[CHANGELOG_STYLE.md](CHANGELOG_STYLE.md) covers the release text.

## Upstream upgrades

Not yet run end to end. See [Not yet exercised](#not-yet-exercised).

1. `.github/workflows/upstream.yaml` checks the latest stable upstream release every six hours and ignores versions at or
   below `upstream_tag` in `.automation/policy.json`. Each new version opens one Issue assigned to the owner, with the
   upstream commit in a marker. The release text is linked, not copied, so its mentions notify nobody. A closed Issue is
   not recreated.
2. The owner comments exactly `OK` or `OK vX.Y.Z`. Comments from anyone else, and Issues the bot did not open, do not
   count. `.github/workflows/upstream-approval.yml` reacts within about a minute, and the hourly pass of `upstream.yaml`
   covers a lost event. Closing the Issue withdraws the upgrade.
3. A clean merge goes on `agent/upstream-vX.Y.Z` with the new `upstream_tag` and `upstream_sha`, and opens a PR that closes
   the Issue when merged. To start over after closing that PR unmerged, delete the branch.
4. `GITHUB_TOKEN` opened that PR, so its workflows wait for approval. Select **Approve workflows to run** in the merge box,
   or close and reopen the PR. A `workflow_dispatch` run does not help, because GitHub does not count its checks towards a
   required check.
5. The owner merges. This publishes nothing: release in a later PR, as in [Releases](#releases).

### Conflicting upstream upgrades

When the approved upstream commit conflicts with `main`, or touches a path in `protected_paths` of
`.automation/policy.json`, nothing is merged or pushed. The Issue gets one comment listing the files and the upstream
commit, and it is not retried. The owner then:

1. Merges that upstream commit on a branch of their own, resolving the conflicts by [FORK_PATCHES.md](FORK_PATCHES.md).
2. Sets `upstream_tag` and `upstream_sha` in `.automation/policy.json` to that version.
3. Opens a PR whose body says `Closes #<Issue>`. Its CI starts by itself, since the owner opened it.

## Dependencies

Dependabot and the scan, with what each one misses: [SECURITY_AUTOMATION.md](SECURITY_AUTOMATION.md).

## Notifications

| Source | What you get | When |
|---|---|---|
| `control.watch` | Issue assigned to the owner | New stable upstream version, one per version |
| `control.open_pull_request` | PR, and an Issue comment with the link | After OK |
| `control.report_conflict` | Issue comment | After OK, on a conflict or protected path, once per upstream commit |
| `scheduler.notify_once` | `[构建待处理]` Issue assigned to the owner | Build on `main` failed and cannot be reused, one per run |
| `windows_release.report` | `[Windows 构建待处理]` Issue assigned to the owner | Windows build or upload of a release failed, one per tag, later runs comment on it |
| Dependabot | PRs, alert emails | Monthly, or when an advisory appears |
| GitHub | Workflow failure email | Scheduled or release run failed |

## Credentials

GitHub Actions has one secret:

| Secret | Used by | Needs |
|---|---|---|
| `ANDROID_DEBUG_KEYSTORE` | `build.yaml`, `sign-existing.yaml`, `windows.yaml` (the one step that signs `update-windows.json`) | The personal signing key. It stays on GitHub only |

Everything else uses `GITHUB_TOKEN`, with permissions declared in each workflow. The repository default is read-only, and
Actions may create pull requests.

## Manual controls

Run these from GitHub Actions on `main`:

- `upstream.yaml`, `operation`: `watch`, `approvals`, `scheduler`, `all`.
- `build.yaml`: `source_ref` must be the current `main`. `reuse_run` takes a run whose artifact to reuse.
- `sign-existing.yaml`: signs the artifact of an earlier run.
- `windows.yaml`: `release_tag` empty compiles the selected ref and keeps the packages on the run. `release_tag` set, on
  `main`, builds that Release's target commit and adds the Windows files, unless it already has all three.

## Changing the process

A change to `.github/` or `.automation/` is an ordinary PR, with the same checks and the owner's merge.

- Update this file or `SECURITY_AUTOMATION.md` in the same PR, and rewrite whatever went stale rather than adding to it.
- Run the checks first:

  ```bash
  python3 -m unittest discover -s .automation -p 'test_*.py'
  python3 -m unittest tool.test_release_identity
  uvx --from actionlint-py actionlint .github/workflows/*.y*ml
  ```

- The scan runs its scanner from `main`, so a PR that changes the scanner does not exercise its own change.
- `upstream.yaml` and `upstream-approval.yml` run the `.automation` tests on `main` before they change anything, so a red
  test on `main` stops upstream handling.

## Not yet exercised

Unit tests and read-only dry runs cover these. None has run for real:

- The upstream path from OK onwards: the `issue_comment` trigger, the bot's push and PR, `Closes #<Issue>`.
- The checks of a bot PR, after **Approve workflows to run**, satisfying the required checks.
- Dependabot security updates on `/core`, and the Cargo patch-only rule.
- `windows.yaml` beyond the PR build and smoke test: the `workflow_run` trigger, `release_tag`, `Windows publish`, signing
  with the real key (a throwaway key in both store formats goes through the same code in the unit tests), the failure Issue,
  and whether a recovery run of `build.yaml`, which `GITHUB_TOKEN` dispatches, fires `workflow_run` at all. If it does
  not, run `windows.yaml` with `release_tag`.
- The in-app Windows update on a real desktop: UAC, the download through the proxy and the relaunch after an update
  from a real earlier version. The smoke test installs with the same arguments, without UAC, over the same version.
