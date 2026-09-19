# Dependency security automation

The daily GitHub `Dependency security` workflow resolves the Go module graph in
`core` and reads both Rust lockfiles, then queries the OSV database. CNB's existing
findings add priority information; their old revision is not treated as a fresh
scan. Reports are retained as workflow artifacts for 14 days. Local replacements
and Git dependencies without an indexed version are explicitly listed as unscanned.
This inventory scan does not prove platform reachability or exploitability.

Signed CNB Issues group findings by dependency and file, deduplicating advisory
aliases. At most ten new Issues and two developer NPC requests are started per run;
the daily schedule drains the backlog. Identical advisory sets are not repeatedly
sent to the NPC. New advisory sets can request another assessment of that group.
Closing an Issue manually pauses further automatic work for that group.

The development NPC must verify primary advisories, actual selected versions,
Go call paths (including mihomo's local replacement) and Rust target conditions.
It may create a minimal compatible dependency-update CNB PR and run focused tests.
Major upgrades, missing fixes, compatibility uncertainty or failed validation require
a human decision. It cannot ignore findings, disable checks, merge or release.

CNB PRs run the official incremental SCA plugin (new High/Critical findings block),
Go regression tests, Rust helper/API tests, and the existing paired review gate.
GitHub PRs with dependency changes compare complete OSV scans of base and head;
new advisory matches fail the scan, including findings with unknown severity. GitHub scans
use the scanner from trusted main and never give PR code the monitoring secrets.
These jobs do not compile APKs. The Linux Rust tests do not replace platform-specific
Windows/macOS/Android validation; reviewers must identify those remaining gaps.

A security Issue is automatically closed only after a complete scan of current main
no longer finds that dependency's known vulnerabilities (or the dependency was
removed). A local/unindexed replacement cannot produce that automatic clean result.
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
