# CNB Android development

The private CNB repository mirrors the personal log-history changes at commit
2b42418. The original GitHub workflows remain unchanged.

## Workflows

- Push to main or use the build button to analyze, run focused tests and build an ARM64 APK on 8 CPUs.
- Pull requests run analysis and the focused tests on 4 CPUs.
- Cloud development opens a 4-CPU WebIDE using the same pinned SDK image.
- APK, SHA-256 and per-stage timing CSV files are attached to the commit for 14 days.

The first run builds the SDK image. Later runs reuse it if the Dockerfile is unchanged.
Dependency directories use CNB copy-on-write caches. Repository build outputs are not cached,
so a subsequent job is not equivalent to an incremental build in a long-lived development session.

## Signing

CNB creates a disposable benchmark signing key. No personal Android signing private key
is uploaded. These APKs cannot update the previously signed personal app. Do not uninstall
the existing app to install benchmark artifacts: its local data would be lost.
Production signing can be added separately with a CNB secret repository.

## Measuring usage

Allocated CPU count multiplied by billed elapsed hours gives core-hours. Idle WebIDE time
also counts. Record the organization's usage before and after each isolated run, and compare
against the per-pipeline duration. Image preparation, dependency downloads and compilation all
contribute to first-run cost; timings.csv reports script stages only.
Stop cloud development after use. The configured jobs have explicit execution timeouts.

## Measured results, 2026-09-19

The successful run is `cnb-ujg-1k2sp1lam`, commit `1a1fa7b`, on 8 CPUs / 16 GiB.
It completed in 17m47s wall time. The organization billing delta was 8,480 core-seconds,
or **2.3556 core-hours** (17m40s at 8 CPUs). Scheduling and cleanup explain why the
wall-clock duration and billed duration are not identical.

| Stage | Elapsed |
| --- | ---: |
| Cached SDK image / runner preparation | 55.4 s |
| Project dependency preparation | 39.9 s |
| Go tests, vet, Flutter analysis and focused tests | 125.1 s |
| ARM64 release APK and signature verification | 773.9 s |
| Upload APK, checksum and timings | 3.8 s |

The APK is 61,636,426 bytes. SHA-256:
`d9a055df64cacc9897029f3a174b2db821e2330b02b4d6f8bb97caaa95ee1bbc`.
Artifacts are available on the successful build/commit page for 14 days.
This is a cached-toolchain, cold-project build, not an incremental build benchmark.
The tested image is cached remotely, but module downloads still occurred on this runner.
Android platform 35 and CMake 3.22.1 were installed by Gradle during this run.

Two setup attempts consumed **1.9444 core-hours** combined:

- `cnb-mkg-1k2so0sr9`: 0.5044 core-hours, Flutter archive UID extraction incompatibility.
- `cnb-078-1k2soa0vm`: 1.4400 core-hours, built the reusable SDK image, then exposed a Go test requiring an unprivileged user.

The fixes are `TAR_OPTIONS=--no-same-owner` and running the compiled Go test binary as
`nobody`, without skipping the permission assertions. The successful SDK image preparation
in the second attempt took 548.5 seconds. Setup attempts are not recurring normal-build costs.

Cloud development run `cnb-9so-1k2sor5tm` used 4 CPUs / 8 GiB, loaded the source in WebIDE,
and prepared dependencies. It was explicitly stopped after 3m41s wall time; the billed
delta was 844 core-seconds, **0.2344 core-hours**. No development environment was left running.

Total for this migration and experiment: **4.3000 build core-hours + 0.2344 development
core-hours**. Baseline organization usage was 213 build / 343 development core-seconds;
after settlement it was 15,693 / 1,187 respectively. No concurrent jobs in this organization
were running during the measurements. SDK image and APK increased object storage by about
2.90 GiB. These numbers describe this workload and observed network/cache state only.

At the measured full-build rate, the 160 build core-hours monthly allowance covers about
67 complete builds. The 1,600 development core-hours allowance covers 400 hours at 4 CPUs.
