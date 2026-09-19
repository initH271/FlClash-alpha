# FlClash-alpha automation

## Owner decision and upstream tracking

GitHub's `Upstream decisions and build scheduling` workflow checks official stable
upstream Releases every six hours. It ignores prereleases and versions at or below
`.automation/policy.json`. Each upstream version creates one CNB Issue assigned to
Aharon, including a fixed upstream commit and a signed authorization record.
Closed upgrade Issues are not recreated. The upstream NPC writes an analysis.

Every 15 minutes the controller checks pending decisions. An exact standalone
`OK` or `OK vX.Y.Z` comment by the real Aharon account approves only that Issue's
fixed version. NPC comments, other users, quoted/longer messages, and modified
signed records cannot approve. Closing the Issue withdraws pending approval.

A clean merge creates an upgrade branch and draft PR. The candidate source tree
is signed, then waits for both independent PR reviews before testing and compiling once.
All Flutter tests run for candidates.
Publication rechecks the source tree, owner approval, unchanged main and PR reviews. Only then
is main fast-forwarded, synchronized to CNB, and the fixed-key APK released.
Conflicts and upstream changes to automation/CI require a draft PR and human
review; the development NPC works on a branch. Failed tests stop publication and
create an Issue for the review NPC. No phone installation is automated.

## NPC roles and permissions

`.cnb/settings.yml` defines 上游更新助手, 开发助手, 审查助手 and GLM复核助手.
DeepSeek roles explicitly use deepseek-v4.1-flash; the independent reviewer uses
glm-5.3-flash. NPC tasks use 2 CPUs, with a maximum of 60 turns per reviewer.
Main is protected on CNB: ordinary developers/NPCs cannot push directly;
PRs require administrator approval and passing checks. The owner account's scoped
automation token may synchronize main. Personal signing stays on GitHub.

## One build, two download channels

GitHub standard public runners are primary. The scheduler first reuses an APK
artifact for the exact source commit and build number after publication failures.
A normal build with an already-published commit is skipped. Reusing a published
build number for a different commit is rejected before compilation.

Queued jobs older than ten minutes are cancelled by the controller. A later pass
must confirm completion before fallback. The polling interval is 15 minutes, so
this is a threshold, not a ten-minute response-time guarantee. Manual cancellation
is respected. Startup/setup faults and explicit disk/runner failures can fail over;
ordinary compile errors, tests and ambiguous timeouts go to diagnosis instead.
Recovery attempts are deduplicated and never recursively retried.

CNB fallback requires at least seven free build core-hours and uses an 8-CPU
runner, with a 50-minute orchestration deadline. It tests and compiles the exact
commit, uploads a temporary draft artifact (one-day retention), and never receives
the personal signing key. GitHub verifies source/version/hash, applies the fixed
personal signature, and publishes. The waiting GitHub runner performs no duplicate
compilation. If GitHub is completely unavailable, final signing/publication waits
for recovery; the system does not claim total platform independence.

Release publication triggers CNB synchronization immediately. The existing
15-minute mirror schedule remains as a recovery path. Both public channels serve
the same signed bytes. `APP_ENV=stable` removes the PRE banner without changing
the compatible com.follow.clash.dev package ID.

## Credentials and notification delivery

GitHub Actions Secrets:
- ANDROID_DEBUG_KEYSTORE: existing personal signing key.
- UPSTREAM_APPROVAL_KEY: authorization-record integrity key; generated once.
- CNB_AUTOMATION_TOKEN: scoped to 507space/FlClash-alpha, with code/Issue/comment
  read/write, PR read/comment write, build trigger/history and Release read permissions. Quota inspection
  additionally needs group-resource:r. It is never committed or printed.

Notifications are CNB Issues assigned to Aharon and their comments, with an
optional user-configured CNB notification delivery channel. No enterprise WeChat
Webhook or external messaging account has been configured. Approval is entered
on the relevant CNB Issue. Expired/insufficient tokens fail the workflow visibly.

Manual controls live in GitHub Actions:
- upstream.yaml: watch / approvals / scheduler / reviews / all.
- build.yaml: source_ref (exact approved SHA), reuse_run or cnb_fallback.

Validation: `python -m unittest discover -s .automation -p 'test_*.py'` plus the
existing mirror tests and CNB schema validator. Failure switching is tested with
fixtures rather than deliberately duplicating a full build or exhausting quota.

Initial verification (2026-09-20): the controller created CNB Issue #1 for upstream
v0.8.98, assigned it to Aharon, and left approval pending. The upstream NPC ran
successfully using deepseek-v4.1-flash: 0 billed AI Credits, about 0.03 development
core-hours. The `preflight` manual controller operation checks CNB release read,
quota, Issue/comment access and mirror trigger/status permissions without building.

Final integration verification: GitHub run 35455547751 passed the complete CNB
preflight, including creating and deleting a temporary unpublished Release/tag
through a delegated runner token. No extra token permissions were required.
The earlier immediate mirror returned HTTP 403; the scheduled recovery published
2026094003 successfully. Error reports now identify the host and sanitized reason.
GitHub release run 35454382586 succeeded. Source/version/ARM64 runtime and personal
certificate checks passed for the downloaded 2026094003 APK. Main-branch protection
and actual upstream NPC replies were also verified. Heavy CNB fallback compilation
was not deliberately exercised because that would duplicate a successful build.

## DeepSeek and GLM paired reviews

Existing roles explicitly use `deepseek-v4.1-flash`. The new `GLM复核助手`
role routes to `glm-5.3-flash` for both Issue and PR mentions, with 128k context,
60 turns, the platform minimum 48k maxTokens setting and a ten-minute stage timeout.
Only its GLM stage runs; other roles run only the DeepSeek stage. Both use
2-CPU NPC runners. These model IDs were verified against CNB's official
npc/CodeBuddy configuration. GLM usage is billed separately in AI Credits;
DeepSeek's current promotional zero billing does not imply free GLM usage.

New upstream decision Issues ask the upstream DeepSeek role and GLM to review
the same fixed upstream range independently. Every open GitHub or CNB PR receives
a separate signed review Issue for its platform, PR number and exact base/head.
The PR receives a link to the two reports. No APK is built by either reviewer.

Reports must identify commit range, evidence, blockers, disagreements and
unverified behavior. Reviewers first inspect code themselves, then compare
reports. They must not summon each other or loop through repeated reviews.
Human-triggered follow-ups should name a new commit range when code changes.
Upstream decision reports remain advisory. PR reports are required gates, in
addition to owner OK and deterministic tests. Only reports authored by each exact
NPC identity, with the matching request digest and a machine-readable pass with
zero blockers, can pass. Missing, malformed or blocking reports cannot pass.
Closing a review Issue blocks that scope rather than silently requesting it again.
Conflicts remain for human resolution.

GitHub PR opened/reopened/synchronize/edited events trigger a trusted-main
controller. The 15-minute controller also discovers CNB PRs, bot-created GitHub
PRs and base changes, and refreshes results without rerunning existing requests.
New base/head means a new review; old passes cannot authorize candidate promotion.
GitHub main requires the FlClash/paired-review status and an up-to-date branch.
CNB pull_request.target runs the target branch's gate, waiting up to 30 minutes
for both reports. Its existing required-status-check protection blocks merging.
After a timeout or a corrected blocking report, rerun the CNB PR gate. No automatic
repair loop or review retry is enabled. The one-CPU waiting runner can consume up
to 0.5 core-hours per CNB PR event; GitHub result polling uses the existing schedule.

Candidate construction no longer dispatches a release build immediately. The
controller resumes it only after both reports pass, and promotion checks the
reports again. GitHub PR status writes and reviews run without checking out or
executing PR code. CNB gates accept requests only from the configured owner; the
GitHub controller additionally verifies their HMAC. Owner/admin credentials remain
trusted, as they already control repository settings and release automation.

GLM-5.3-Flash is the default independent reviewer, including image support.
Full GLM-5.3 may be considered for complex changes or unresolved disagreements;
it is not automatically invoked as a third reviewer.

GLM should finish evidence gathering by approximately turn 45 or eight minutes,
then reserve the remaining budget for its report. Batch related reads and reuse
verified facts. An incomplete review must report uncertainty and cannot pass;
this is a prompt-level stopping strategy, not a guaranteed pre-timeout callback.
