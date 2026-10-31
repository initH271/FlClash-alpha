# Dependency security automation

Two things watch the dependencies. Neither of them merges anything: the owner does.

## Dependency vulnerability scan

`.github/workflows/security.yaml` runs on every push to main, every day and on every pull request. It runs
`.automation/security_scan.py` when the change touches a `go.mod`, `go.sum`, `Cargo.toml` or `Cargo.lock`, `.gitmodules` or
`core/Clash.Meta`, and on a push or schedule always. The scan reads the resolved Go module graph of `core`, mihomo's
dependencies included, and both Rust lockfiles, and queries OSV.

On a pull request it compares complete scans of base and head, and a new advisory match fails the job, whatever its
severity. The job is the required check `Dependency vulnerability scan`. The scanner comes from main, so PR code cannot
change it, and it uses no secrets. A scan that cannot reach OSV exits 75 and leaves no report, so it never reads as
clean. Reports stay as workflow artifacts for 14 days.

Local replacements and Git dependencies without an indexed version are listed as unscanned. The scan does not prove
reachability or exploitability, and nothing tracks a match on main: read the report, or the Dependabot alerts.

## Dependabot

Alerts and security updates are on in the repository settings. `.github/dependabot.yml` sets a weekly schedule, Monday
09:00 Shanghai, with version and security updates grouped per ecosystem. CI starts on these PRs by itself, and the NPC
review skips them.

| Ecosystem | Directories | Version updates | Security updates |
|---|---|---|---|
| `pub` | `/` and the plugins with external dependencies | All | Yes |
| `gomod` | `/core` | **Off** (`open-pull-requests-limit: 0`) | Yes |
| `cargo` | `/services/helper`, `/plugins/rust_api/rust` | **Patch only** (`allow` with `update-types`) | Yes |
| `gradle` | `/android`, `/plugins/wifi_ssid/android` | All | Yes |
| `github-actions` | `/`, `/.github/actions/setup-android-toolchain` | All | Yes |

`open-pull-requests-limit` counts version updates only: security updates have their own fixed limit of 10. `allow`
`update-types` also limits version updates only. Raise Cargo minor versions by hand: a group is all or nothing, and one bad
minor release sinks every other update in it.

### Fix versions in `core/go.mod`

`core/go.mod` holds fix versions of modules that mihomo pulls in, marked `// indirect`: go-jose, goldmark, otel/sdk,
genproto, grpc and others ([FORK_PATCHES.md](FORK_PATCHES.md) G4). The build picks versions from this file, so these lines
are what lifts them. `go mod tidy` removes them, the versions fall back to what mihomo asks for, and the advisories return.
That is why `/core` version updates are off.

After `go mod tidy` in `core`, run `git diff core/go.mod`. Restore any fix version that went missing or went down.

A Dependabot security update on `/core` goes through the same updater, so it may drop these lines too. This has not been
seen yet. The required scan fails such a PR. Make that bump by hand instead.

### What Dependabot misses in `core/Clash.Meta`

`core/Clash.Meta` is a submodule with its own `go.mod`, which is not in this repository, so Dependabot cannot read it.

- The pinned commit is not Dependabot's: `gitsubmodule` would go to the tip of the `FlClash` branch, ahead of the upstream
  release and around the owner's OK. It only moves with an upstream upgrade.
- Mihomo's dependencies appear in `core/go.mod` as `// indirect`, so security updates and alerts see them there.
- Only the scan reads the complete resolved graph.
- Mihomo's own code has no advisory coverage, from Dependabot or from the scan. Only following upstream moves it.
