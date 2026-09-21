# FlClash-alpha — Rolling core log history

This personal build is based on FlClash v0.8.97. The live log view keeps its
5,000-record limit; core history is independent of that view and its subscription.

The core starts a bounded disk recorder during initialization. It records the
configured log level (including DNS and handshake details at `debug`) into
`log-history/` under the application's private data directory. Each JSON Lines
segment is limited to 5 MiB. At most ten segments are retained, oldest first.
Restarting appends to the latest segment; an incomplete trailing line left by a
crash is removed before appending. Each record includes a timestamp with timezone.

The log page has one **Export all logs** button. It exports one ZIP containing
all retained core history, rolling Flutter `[APP]` history under `app/`, and a
`recent-ui.log` snapshot. The snapshot may overlap the historical records.
APP history also retains ten 5 MiB segments, survives restart, and is recorded
at the application's logging entry point rather than from the UI's 5,000 entries.
Logging cannot recover events from before installing this build or expired segments.

Writes are buffered and flushed every second, on export, and on graceful shutdown.
An abrupt process kill may lose the final buffered records. The recorder uses a
bounded queue so slow storage cannot block proxy connections; if that queue fills,
it records an explicit dropped-record warning. Individual messages longer than
32 KiB are marked as truncated. Disk errors are reported to stderr and surfaced
on history export, rather than reporting a complete archive after lost writes.

The two histories occupy at most 100 MiB combined, plus temporary export archives and the
user's saved exports. User exports are not automatically deleted. The private
history is removed with app data/uninstallation; export it before uninstalling.
APP writes run sequentially in a bounded queue; export waits for earlier writes.
Abrupt termination can lose queued APP records. Storage errors fail the complete
export explicitly. Compression runs in an isolate to keep the UI responsive.

## Checks

- `cd core && go test ./internal/logstore`
- `cd core && CGO_ENABLED=0 go test .`
- `cd core && CGO_ENABLED=0 go vet .`
- `flutter analyze --no-fatal-infos`
- `flutter test test/core/protocol_contract_test.dart test/views/logs_view_test.dart`
- `flutter test test/common/log_history_test.dart`

For Flutter-only tests, temporarily disable the two native build hooks as described
in `.agents/commands.md`, then restore them before building an APK. No generated
provider/model files change; ARB changes are generated with `dart run intl_utils:generate`.

## Android verification

Build an arm64 APK using the repository's pinned toolchains. Without upstream
signing keys, the existing Gradle configuration produces the `.dev` application
alongside the official app. Import a backup into that app before testing; do not
uninstall the official app or run both VPNs at once.

Verify capture with the log page closed and with the UI backgrounded. Generate
more than 5,000 records, restart the app, export history, and check that records
from before the restart remain. Also verify file rotation and a cancelled export.
Native Android background behavior and the save dialog require device testing;
host unit tests do not establish those guarantees.

## Local validation status (2026-09-19)

The Go storage and core tests and Go vet passed for the core recorder. All 17
targeted Flutter storage/protocol/UI tests passed for the unified export,
including 5,101 APP records across restart, rotation, partial-line repair, and
export failure/retry. Targeted Dart analysis reported no issues. Earlier full
Flutter analysis passed with one existing `prefer_const_constructors` info in
`test/widgets/scrollbar_inset_test.dart`.
The Android ARM64 core also compiled successfully as a shared library with
`with_gvisor`, using the host's Go 1.25.1 and NDK 27.1.12297006. This is a platform
compile check, not a release build with the upstream pinned toolchains.

The Windows toolchain prerequisites are now installed, but the local APK build
still fails in the Rust native-assets hook. Android Rust cross-compilation passed
when invoked directly. Device verification remains pending.

## GitHub Actions

The private repository `initH271/FlClash-alpha` builds the Android ARM64 APK
on pushes to `main` and manual workflow dispatches. The workflow pins the upstream
Flutter 3.47.1, Go 1.26.8, NDK r28c, Java 17, and Rust 1.95.0 toolchains. It runs
core tests, Go vet, Flutter analysis, and the focused log export tests before
building. The APK and SHA-256 checksum are retained as an Actions artifact for
14 days. The original multi-platform workflow is preserved outside the active
workflow directory at `.github/upstream-build.yaml`.

The release build keeps the upstream `.dev` application ID behavior. A dedicated
personal signing key is restored from the `ANDROID_DEBUG_KEYSTORE` repository
secret, allowing subsequent CI builds to update the same custom application.
The private key is not committed. Build numbers increase with the workflow run
number. Backups retain the upstream format; restore and background logging must
still be checked on the phone.

## Verified CI artifact (2026-09-19)

Build run 35438550695 completed successfully, including the focused tests and
release APK. Signing run 35439886063 re-signed that artifact with the dedicated
personal key and verified its certificate. The build workflow now performs that
explicit signing check before every upload. The signing-only workflow can also
process an existing build without recompiling.

The downloaded APK passed SHA-256 and Android signature verification. Its package
is `com.follow.clash.dev`, version 0.8.97, version code 2026093006, and size
61,636,426 bytes. App, Flutter, Go core, and Rust libraries target ARM64; some
transitive Android dependencies also contain unused libraries for other ABIs.
The signing certificate SHA-256 is
`4cc5094e24f4a4cfde3a37d6c839ae376bd74c50075d8ee6bc73e25682e9afad`.
The phone was disconnected at delivery, so no installation or device test was run.
