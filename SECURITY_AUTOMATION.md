# Dependency security automation

Two things watch the dependencies. Neither of them merges anything: the owner does.

## Dependency vulnerability scan

`.github/workflows/security.yaml` runs `.automation/security_scan.py` on every push to main, every day, and on pull
requests that change Go or Rust dependencies or `core/Clash.Meta`. It reads the resolved Go module graph of `core`,
mihomo's dependencies included, and both Rust lockfiles, and queries OSV.

On a pull request it compares complete scans of base and head, and a new advisory match fails the job, whatever its
severity. The job is the required check `Dependency vulnerability scan`. The scanner comes from main, so PR code cannot
change it, and it uses no secrets. A scan that cannot reach OSV exits 75 and leaves no report, so it never reads as
clean. Reports stay as workflow artifacts for 14 days.

Local replacements and Git dependencies without an indexed version are listed as unscanned. The scan does not prove
reachability or exploitability, and nothing tracks a match on main: read the report, or the Dependabot alerts.

## Dependabot

`.github/dependabot.yml` opens weekly grouped PRs for pub, Go, Cargo, Gradle, GitHub Actions and the mihomo submodule.
They go through CI like any other PR. Alerts and security updates are repository settings the owner turns on.

`core/Clash.Meta` has its own `go.mod`, which Dependabot cannot read because it is not in this repository:

- `gitsubmodule` moves the pinned commit to the tip of the `FlClash` branch. It compares nothing and knows no advisory.
- `/core` updates `core/go.mod`, where the build picks its versions, so a bump there also lifts what mihomo requires.
  Version updates stick to direct dependencies. Mihomo's dependencies are indirect there and rely on security updates.
- Mihomo's own code has no advisory coverage from either. Only following upstream moves it.
