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

`security_finish.py` serializes completion with the existing controller lock:

1. Only same-repository, non-draft `security/group-*` PRs linked to a signed open
   master Issue are candidates. Allowed files are core/go.mod + go.sum or the
   group's Cargo.lock. Toolchain/replace changes, manifest/source/CI edits, version
   downgrades, major upgrades, 0.x minor upgrades and ambiguous multi-version Rust
   transitions require manual review. A go.sum-only edit is not auto-merged.
2. Both signed current-scope NPC reports must pass. The native vulnerability,
   Go, Rust and paired-review checks must all exist and succeed. The tested
   pre-merge commit tree must equal `git merge-tree` for the current base/head.
3. The controller rechecks the PR before and after approving and uses normal CNB
   merge with force=false. CNB's merge API has no expected-head parameter, so the
   final server-side protection checks remain essential; protection is never
   disabled. One merge is processed per pass, with mirrors completed before another.
4. A signed GitHub mirror PR preserves CNB history. The GitHub merge uses its
   expected SHA. Only identical baseline AND result trees, a valid signed mirror,
   same-repository branch, and original successful paired-review/CI evidence allow
   review reuse. Otherwise ordinary GitHub review is required. There is no synthetic
   NPC report and no APK rebuild. Out-of-policy mirror changes are explicitly reported.
5. GitHub main is fast-forwarded back to CNB without checkout of PR code. A complete
   scan is requested once per current main; running/successful scans deduplicate it,
   and two failed runs stop with an explicit controller error. Scan results alone
   close fixed master Issues; remaining findings stay open.

An unsuccessful read fails visibly and is reconciled on the next pass. An
uncertain CNB approval/merge response records one stop notice for that head; the
controller will not repeatedly write reviews or retry a permission failure.
Dispatching a new workflow with GitHub's token is explicit because token-created
PRs do not automatically emit all workflow events. The existing CNB automation
token needs PR read/write and review permission in addition to its scan/Issue scopes;
missing permission is a deployment failure, not a reason to bypass a gate.

Both trusted controller workflows run the Python test suite before any mutation.
Hard model-token/credit caps and replacing the CNB waiting runner with a native
asynchronous status integration remain separate work; this implementation does
not claim either feature. The 30-minute gate can accept a corrected report while
waiting, but a final timeout still requires a gate rerun.
