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

Each group has one branch and developer task. An open group PR or running developer
prevents a second worker; at most two groups start per scan. Identical advisory sets
are not repeatedly dispatched. Closing a master Issue manually pauses it. A group
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
PR gate. Approval to merge or publish dependency repairs is not granted by this monitor.
