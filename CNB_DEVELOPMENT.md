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
