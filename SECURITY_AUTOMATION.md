# Dependency security automation

The daily GitHub `Dependency security` workflow resolves the Go module graph in
`core` and reads both Rust lockfiles, then queries the OSV database. CNB's existing
findings add priority information; their old revision is not treated as a fresh
scan. Reports are retained as workflow artifacts for 14 days. Local replacements
and Git dependencies without an indexed version are explicitly listed as unscanned.
This inventory scan does not prove platform reachability or exploitability.

Three signed CNB master Issues group work by dependency graph and verification scope:
Go core (including mihomo dependencies), Rust Helper, and Rust API. Each keeps a
per-advisory scan history; identical CVEs affecting different packages remain distinct.
Old component Issues are linked and closed as consolidated (`not_planned`), never
reported as fixed merely because they were consolidated. Manual notes outside the
managed scan snapshot are preserved.

Each group has one branch and a persistent signed dispatch receipt in its master
Issue. The controller reads developer executions from both the master Issue and
its same-repository repair PR. At most two groups may have running or unconfirmed
workers; untouched groups take available slots before failed groups are retried.
Daily scanning updates the inventory; the controller can advance that existing
inventory without rescanning or waiting until the next day. Identical advisory
sets receive at most an initial dispatch and one automatic continuation. A new
commit does not reset the continuation budget. Manually summoned platform workers
are observed but are not included in that automatic dispatch budget.

A failed run without a report may continue from the existing branch/PR after its
terminal status is checked. A second failure becomes a visible manual-action state.
A merged PR waits for a complete main-branch scan; a closed unmerged PR does not
restart automatically. Running workers exceeding 30 minutes remain reserved and
are shown as stalled; this version never launches a competing worker or kills a
run based only on elapsed time. A dispatch without a platform receipt also keeps
its slot until manually resolved. Managed progress text preserves manual notes
and scan signatures. Reconciliation is serialized with the existing GitHub
controller concurrency group; it must not be run concurrently outside that group.

Developer prompts request one bounded phase, an existing branch checkpoint and
actual test evidence. The 12-tool/5-minute prompt is advisory; maxTurns remains
the platform's enforced bound. These are not yet a hard token/credit cap or a
fully automatic multi-phase implementation engine. Closing a master Issue manually pauses it. A group
automatically closed after a clean scan reopens when new findings appear.

The development NPC must verify primary advisories, actual selected versions,
Go call paths (including mihomo's local replacement) and Rust target conditions.
It may create a minimal compatible dependency-update CNB PR and run focused tests.
Missing fixes are recorded per finding while other compatible repairs may proceed.
Group-wide major upgrades, toolchain changes, compatibility uncertainty or failed
validation require a human decision. It cannot ignore findings, disable checks,
merge or release.

CNB PRs run the official incremental SCA plugin (new High/Critical findings block),
Go regression tests, Rust helper/API tests, and the existing paired review gate.
The Go pipeline also runs full baseline and head OSV scans for `security/group-*`
branches. Partial repairs may pass only if at least one existing advisory match
is removed, no new matches appear, and indexed dependencies are not hidden behind
unindexed replacements. Remaining findings stay in the master Issue, with separate
assessment evidence in its discussion. Legacy `security/fix-<hash>` branches retain
their original full-clear requirement.
GitHub PRs with dependency changes compare complete OSV scans of base and head;
new advisory matches fail the scan, including findings with unknown severity. GitHub scans
use the scanner from trusted main and never give PR code the monitoring secrets.
These jobs do not compile APKs. The Linux Rust tests do not replace platform-specific
Windows/macOS/Android validation; reviewers must identify those remaining gaps.

A security Issue is automatically closed only after a complete scan of current main
no longer finds the group's tracked vulnerabilities (or their dependencies were
removed). Unindexed replacements of tracked dependencies prevent automatic closure;
an unrelated pre-existing local module does not hide progress on other packages.
PR merge alone and NPC assertions cannot close the security finding. CNB's historic
dashboard is not edited or marked ignored; its own scanner updates it independently.

Monitoring failures, truncated responses and a main change between scan and tracking
stop updates rather than reporting a clean result. `CNB_AUTOMATION_TOKEN` needs
repo-code read and Issue/comment read-write permissions. GitHub's existing approval
key signs tracking records; no additional credentials are introduced.

Automatic repair PRs are opened on CNB, where required status checks enforce both
the scan and regression tests. GitHub's additional PR scan is diagnostic; its result
is not a new required branch-protection context, because bot-created upstream PRs
do not emit ordinary pull_request workflow events. It does not replace CNB's repair
PR gate. The owner has enabled `security_auto_merge` for compatible, dependency-only
repairs. NPCs still cannot merge or release; the trusted controller is the only
automatic merger, and APK publication is not authorized by this policy.


## Verified completion and further repair rounds

The signed inventory records its scanned main SHA. A merged repair only allows a
new advisory revision to start after GitHub confirms that the repaired head is an
ancestor of that scan. Earlier execution statuses are excluded from the new round;
an unchanged advisory set cannot reset an already consumed continuation budget.
A manually closed, unmerged PR remains paused. Compatible groups may refresh their
branches by a conflict-free ordinary merge of main when no developer is running.

`security_finish.py` serializes completion with the existing controller lock.
GitHub is the sole merge authority. CNB hosts repair branches, native tests and
paired-review records; its PRs are validation records, not a second approval gate.
The controller never calls CNB approval or merge APIs.

1. Same-repository, non-draft group PRs must link to a signed open master Issue.
   Auto-forwarding allows only the group's lock/module files and conservative
   compatible version changes. Source, toolchain, replace and major/0.x minor
   changes require a reviewed integration PR on GitHub.
2. The current CNB base/head must have both signed NPC passes and all four native
   checks. The CI pre-merge tree must equal the actual merge-tree. If a compatible
   branch is behind, only a conflict-free normal merge refreshes it, and only when
   no developer task is running.
3. A signed GitHub PR points to the exact tested CNB head, with the same base SHA
   and tree. Current matching native CI and NPC evidence may satisfy paired review
   without running models or builds a second time. Any changed source, base, tree,
   draft state or invalid signature prevents reuse. GitHub merge pins the head SHA
   and still obeys its required status checks; no force or protection override.
4. After GitHub merges, CNB main is fast-forwarded only. A diverged CNB main raises
   an error, never imports changes back into GitHub or overwrites either side.
   A CNB validation PR is closed only when its head is an ancestor of GitHub main.
   This records integration via GitHub, not a fabricated CNB approval.
5. A complete scan is requested once per current main; running/successful scans
   deduplicate it, and two failed runs stop with a controller error. Only scanning
   closes fixed master Issues. Closed CNB validation PRs included in a signed scan
   can advance remaining findings to a new repair round.

The existing token needs PR read/write to close validation PRs, but no CNB approval
permission is needed. GitHub Actions needs contents/PR/status write permissions.
Token-created GitHub PRs explicitly invoke review reconciliation because normal
PR workflow events may be suppressed. A manually closed GitHub forwarding PR stays
paused; the controller does not recreate it. APK publication is not part of this flow.

Both trusted controller workflows run the Python test suite before any mutation.
Hard model-token/credit caps and replacing the CNB waiting runner with a native
asynchronous status integration remain separate work; this implementation does
not claim either feature. The 30-minute gate can accept a corrected report while
waiting, but a final timeout still requires a gate rerun.
