# Commands

`make` is the entry point on macOS and Linux: `make help` lists every target with its variables, generated from the
`##` comments in the `Makefile`, and `test/tool/makefile_test.dart` keeps the two in step. Each target only calls the
command this file documents, so the logic stays in `tool/`; `make doctor` names a missing toolchain, `make check` is
CI's `dart` job, `make core-check` and `make core-test` the Go wrapper checks CI runs, and `make run` starts the safe mode
build, the only kind a shared host may run.

## Building

Update submodules first. The ClashMeta Go core lives in `core/Clash.Meta/`, the UI library in `plugins/prism_ui/`.

```bash
git submodule update --init --recursive
```

Full package build, including Go core, Flutter, and packaging, runs through `tool/package.dart` (`make package`,
`make package-android`, with `ARCH=`, `FORM=` and `DRY=1`). Run it with `dart`, not `dart run`, which first runs
every build hook for the host:

```bash
dart tool/package.dart                     # this host: dmg, exe + zip, or deb + AppImage + rpm
dart tool/package.dart android             # every ABI; --arch arm64 for one
dart tool/package.dart linux --dry-run --arch arm64   # names and steps only, any platform
```

Artifacts land in `dist/` as `FlClash-<line>-<version>-<os>-<arch>[-<form>].<ext>`, with `manifest.json` and
`FlClash-<line>-<version>-SHA256SUMS`; see Packaging in `architecture.md`.

The desktop Go core and the Rust helper build automatically: Flutter runs
`plugins/setup/hook/build.dart` on every `flutter build` and `flutter test`,
and the hook drives `CoreBuilder` from the `setup_hooks` package in
`plugins/setup/setup_hooks/`. Artifacts land in `libclash/`. Android's Core is
the AAR the `:core` Gradle module builds with `gomobile bind` before anything
compiles against it; that needs `go` on `PATH` and nothing else, since the
gomobile tools come from `core/go.mod` and the NDK from AGP. The hook reruns only when Go, Rust, or
`setup_hooks` inputs change; the fingerprint cache lives in
`.dart_tool/setup_build_cache/`. To force a rebuild, delete that directory:

```bash
rm -rf .dart_tool/setup_build_cache
```

Flutter hides the hook's output on success, so to see why the Core was or was
not rebuilt read `.dart_tool/setup_build_cache/hook.log`; each invocation starts
with a `===` line carrying its timestamp and target.

Both Rust builds, the Helper and `rust_api`, pass `--remap-path-prefix` so no
local path lands in a binary. With neither `RUSTFLAGS` nor
`CARGO_ENCODED_RUSTFLAGS` set, the flags go into `CARGO_TARGET_<TRIPLE>_RUSTFLAGS`,
which Cargo joins with `target.<triple>.rustflags` from a Cargo config but which
leaves `build.rustflags` unread, so put custom flags under the target table.
Either variable set, or a home, checkout or Cargo home path with a space, sends
the flags through `CARGO_ENCODED_RUSTFLAGS` instead, and Cargo then reads no
rustflags from its config.

The hook runs for `flutter test` and for `dart run` of any root-package script
too, so a pure Dart test run needs the Go toolchain, and on Linux and Windows
also `cargo` and `rustc` — the Helper fingerprint shells out to both even on a
cache hit. The hook protocol carries no build mode and no caller, so the only
switch is the user-define in the root `pubspec.yaml`:

```yaml
hooks:
  user_defines:
    setup:
      build_assets: true   # false turns the Go core and Helper hook into a no-op
    rust_api:
      build_assets: true   # false does the same for the Rust library
```

The Flutter job in `.github/workflows/ci.yml` sets both to `false` with `sed` in its throwaway checkout, because no test
loads the Go core. With both off nothing there calls Go, Java, Gradle or the NDK, so it passes `android: 'false'` to
`.github/actions/setup-android-toolchain` and gets only Flutter and Rust. It builds the Rust library with `cargo build --locked` and points `FRB_DART_LOAD_EXTERNAL_LIBRARY_NATIVE_LIB_DIR`
at it, since the editor tests in `test/plugins/code_forge/` and the socket test in `test/core/desktop/ipc_native_test.dart`
load that library.
Never commit `false`: a build with it set stages whatever `libclash/` already
holds and bundles no Rust library, which is why `tool/package.dart` refuses to package
while it is set. Locally, `false` is worth setting for a Dart-only test loop,
but the hook cache keys on the user-define, so the first build afterwards runs
the hooks again. The editor and IPC socket tests still need the Rust library: keep `rust_api`
on, or point `FRB_DART_LOAD_EXTERNAL_LIBRARY_NATIVE_LIB_DIR` at a directory that
holds a `rust_api` library built from the same sources.

## Flutter Development

Use the default Flutter SDK directly:

```bash
flutter pub get
flutter run
flutter test
```

Use `flutter test`, not `dart test`, because models pull in Flutter types.

A development build takes over the host exactly like a release: it creates the TUN device, sets the system proxy, on
macOS registers the TUN as the system resolver, registers itself as the login item, and on Windows and Linux starts its
Core through the shared privileged Helper, which stops the Core an installed FlClash is running. Only the data directory
is kept apart, and only for some builds: a macOS debug build is `com.follow.clash.debug` and an Android debug build `com.follow.clash.dev`,
while profile and release builds, and every build on Windows and Linux, share the directory and preferences of the
installed app. Safe mode keeps all of the host changes off and never opens the Core's listeners or external
controller, so it does not compete with the installed app for the mixed, DNS, RESTful API and other loopback ports:

```bash
flutter run --dart-define-from-file=env.json --dart-define=SAFE_MODE=true
```

`.run/main_safe_mode.run.xml` is the same launch for IntelliJ, and `Flutter App (Safe Mode)` in `.zed/debug.json` (debugger) or `flutter run (Safe Mode)` in `.zed/tasks.json`
(plain run) for Zed. The build is bannered `SAFE MODE`, the tray shows the
`status_4` bug icon with a menu of only show and exit and no traffic title, and the settings keep their values, so
nothing has to be flipped back before a normal run. See the safe mode section of `architecture.md` for the owners that consult the flag.

## Code Generation

Run code generation after modifying models, providers, or database schema:

```bash
dart run build_runner build --delete-conflicting-outputs
dart run build_runner watch
```

Code generation covers:

- Riverpod providers through `riverpod_generator`.
- Models through `freezed` and `json_serializable`.
- Database tables through `drift_dev`.

The Dart-Rust bindings in `plugins/rust_api` are generated by `flutter_rust_bridge_codegen` from
`plugins/rust_api/flutter_rust_bridge.yaml`; rerun it from that directory after changing anything under
`rust/src/api/`:

```bash
cd plugins/rust_api && flutter_rust_bridge_codegen generate
```

Generated output paths, configured in each package's `build.yaml`:

- `lib/models/generated/*.g.dart`, `*.freezed.dart`.
- `lib/providers/generated/*.g.dart`.
- `lib/database/generated/*.g.dart`.

Localizations in `lib/l10n/` come from the ARB files in `arb/` through Flutter's `gen-l10n`, configured in `l10n.yaml`.
`flutter pub get` regenerates them, since `pubspec.yaml` sets `generate: true`; after editing an ARB file alone:

```bash
flutter gen-l10n
```

Tray and Windows app icons are generated, not hand-edited. `assets_source/images/icon/*.svg` is
the source of truth; the script needs `rsvg-convert` (librsvg) on `PATH`:

```bash
dart run tool/generate_status_icons.dart
```

It writes the tray PNGs with Flutter `2.0x/`–`4.0x/` resolution variants to `assets/images/tray/unix/`,
multi-size tray `.ico` files to `assets/images/tray/windows/`, and `windows/runner/resources/app_icon.ico`
from `assets/images/icon.png`. `status_1`–`status_3` are the logo glyph alone and tell stopped, running and TUN
apart only by color, so they carry no rings or shadow. macOS draws its menu bar icon as a template by default,
where color is lost: `status_1` renders the bare logo from `assets_source/images/icon/glyph.svg` and `status_4`
reuses `status_4.svg`, both recolored to black into `assets/images/tray/macos/`; the sources keep their colors.
With the tray menu's monochrome icon turned off, macOS loads the color PNGs from `assets/images/tray/unix/`.
`glyph.svg` is also the geometry of the Android notification drawables
`android/service/src/main/res/drawable/ic.xml` and `ic_service.xml`; change them together. `pubspec.yaml` declares the three tray directories with `platforms:` so each
build only bundles the formats its tray loads; a new status icon needs a source SVG and an entry in the
script's `statusIconNames`, nothing in `pubspec.yaml`.

## Testing

Tests use `package:test/test.dart` for pure Dart logic and `flutter_test` for provider and widget tests. `mocktail` is the mocking framework.

```bash
flutter test test/models/
flutter test test/core/
flutter test test/core/desktop/
flutter test test/providers/
flutter test test/common/
flutter test test/database/
flutter test test/widgets/
flutter test test/setup_test.dart
```

For the whole suite, or a directory of more than a few files, use `tool/test.dart`, which is also what CI runs:

```bash
dart run tool/test.dart                                  # all of test/
dart run tool/test.dart test/widgets test/views          # some paths
dart run tool/test.dart -- --reporter expanded --coverage
```

Plain `flutter test` compiles each file into its own program and starts an engine for it, one file after another, and
that dominates a full run. `tool/test.dart` imports the files into 32 generated entrypoints under
`.dart_tool/test_bundles/` and runs those with one worker per core, about half the time of a plain run, and less than
a third with `--coverage`. Files in one entrypoint share an
isolate, so a test can see state a file before it left behind; the script runs every file that failed there again on
its own, lets that run decide, and names the files that only failed together. See the Shared Test Isolate section of
`rules.md` before fixing one.

`plugins/setup/setup_hooks/` is a pure Dart package and is tested with `dart test` from its own directory;
`tool/check_plugins.sh` does not descend into it. It must stay out of `flutter test`, because a test run of `plugins/setup`
would execute the build hook itself.

`ci-ok` builds Android only. `.github/workflows/windows.yaml` compiles `plugins/*/windows` on PRs that touch native or
build files, as an advisory check, and nothing compiles `plugins/*/{linux,macos}`. `tool/check_plugins.sh` only analyzes
and tests the Dart side.

Root `flutter test` only discovers the root package's `test/` directory by default. Include bundled plugin Dart tests by passing paths explicitly, or run `flutter test` from that plugin package directory, or run `bash tool/check_plugins.sh` to analyze and test every plugin package. Native plugin tests under platform folders are not run by `flutter test`.

The `plugins` job in `.github/workflows/ci.yml` runs the plugin tests and the `setup_hooks` tests, each from its own
package directory. CI does not run `tool/check_plugins.sh`, so it analyzes no plugin from its own directory, and it does not
run the hook tests, `dart format` or a coverage gate. Those mostly guard desktop plugins and appearance. Run them by hand
when you change that code.

For the current Core/service architecture, useful focused checks are:

```bash
flutter test test/core/desktop/
flutter test test/core/service_test.dart
flutter test test/core/protocol_contract_test.dart
flutter test test/manager/core_manager_test.dart
flutter test test/providers/action_test.dart test/providers/system_action_test.dart
flutter test test/views/dashboard/live_status_test.dart
```

What those suites own:

- `test/core/desktop/`: replaceable IPC transport, RPC request correlation/failure, direct/Helper process leases, and
  latest-intent desktop lifecycle convergence. `ipc_native_test.dart` runs the transport over a real socket through
  the Rust `IpcServer`; the server's own behavior is covered by `cargo test` in `plugins/rust_api/rust`.
- `test/core/service_test.dart`: `CoreService` composition and terminal close behavior.
- `test/core/protocol_contract_test.dart`: shared Dart/Go method and event-envelope compatibility, including event batches.
- `test/providers/action_test.dart`: Core start/restart orchestration and overlapping restart requests.
- `test/providers/system_action_test.dart`: ordered, idempotent exit cleanup and watchdog behavior.
- `test/views/dashboard/live_status_test.dart`: 600-millisecond starting presentation hold, immediate failure display,
  the order of the live status deck, where it sits, a list opening in place, and the confirmation before a force
  restart.

`.automation/` holds the release and upstream Python, and its unit tests need Python 3.11 or newer because the security
scan modules read `Cargo.toml` files through `tomllib`; the `Automation unit tests` job in `.github/workflows/ci.yml` runs
the same commands:

```bash
python3 -m unittest tool.test_release_identity
python3 -m unittest discover -s .automation -p 'test_*.py'
```

## Native Component Verification

The CI Go-wrapper checks can be reproduced without CGO. They cover the Android files too, except the cgo one in
`timezone/`, which only the gomobile build compiles:

```bash
cd core
CGO_ENABLED=0 go test .
CGO_ENABLED=0 go vet . ./cmd/...
GOOS=android GOARCH=arm64 CGO_ENABLED=0 go vet -tags=with_gvisor . ./mobile ./tun ./platform
```

The Windows Helper's loopback/session protocol tests are host-independent by default. The `Windows helper test` job of
`windows.yaml` additionally enables its service implementation:

```bash
cargo fmt --manifest-path services/helper/Cargo.toml -- --check
cargo test --manifest-path services/helper/Cargo.toml
cargo test --manifest-path services/helper/Cargo.toml --features windows-service
```

The last command requires Windows for meaningful service coverage. Native Android lifecycle edits should at minimum
compile the modules they touch, with the JDK 17 that CI installs. On macOS the Homebrew `openjdk@17` keg is not
registered with `java_home`, so export it by prefix:

```bash
cd android
export JAVA_HOME="$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home"   # elsewhere: any JDK 17
./gradlew :core:compileDebugKotlin -Ptarget-platform=android-arm64   # builds the gomobile AAR for one ABI
./gradlew :service:compileDebugKotlin
./gradlew :app:compileDebugKotlin
```

Always-on VPN entry, system VPN revoke, actual permission UI, and rapid device start/stop still require Android device or
emulator validation; Kotlin compilation cannot prove those system callbacks.

## Changelog And Release

This fork writes its release text by hand in `.github/release-notes.md`. `tool/changelog.dart`, `CHANGELOG.md` and
`changelog.json` come from upstream and stay for upstream merges: the tool derives the changelog from Conventional Commits,
and `.agents/rules.md` covers the `Changelog:` trailers that decide the wording. CI does not run it.

The app ships no changelog of its own. `render release` appends the released version as JSON inside an HTML comment
(`<!-- flclash:changelog:json … -->`), so the release body GitHub already returns to `checkForUpdate` carries the
notes shown in the update dialog. `parseReleaseChangelog` reads that block and falls back to the plain
bullets when a release predates it.

```bash
dart run tool/changelog.dart verify
dart run tool/changelog.dart release --version 0.8.96
dart run tool/changelog.dart build --unreleased      # changelog.json only, includes untagged work
dart run tool/changelog.dart markdown                # CHANGELOG.md from changelog.json after a hand edit
dart run tool/changelog.dart render release --out release.md
dart run tool/changelog.dart render telegram --out telegram.md
```

Release through a pull request: change `.github/release.json` and `.github/release-notes.md`, and merging publishes. See
[AUTOMATION.md](../AUTOMATION.md#releases). A tag starts no workflow here and `main` takes no direct push, so
`tool/release.sh` and `tool/bump_version.sh`, which come from upstream, have no part in a release.

Wording in `changelog.json` may be edited by hand; `markdown` then rewrites `CHANGELOG.md` from it. In the version being
edited:

- Reword an entry's `text` or `scope`, or write an entry for a commit git would not collect, such as a `refactor`
  users notice; its `id` is any commit in the range.
- `"merges": ["<id>", …]` on an entry folds those commits into it, so they need no entry of their own.
- `"omit": ["<id>", …]` on the version leaves commits out of its notes: internal fixes, or work behind a flag the
  release ships off, such as MITM under `rsFeature`.

`verify` holds every commit git derives to an entry in its group, a merge or an omission, and every id, merge and
omission to the version's range. It also checks the newest version before its tag exists. `release` and `build` keep
every stable version `changelog.json` already records as written and derive only the new one, so an edit outlives
later releases.

Entries at or below `v0.8.96` are frozen: they predate the pipeline, live under the `<!-- changelog:frozen -->` marker
in `CHANGELOG.md`, and are never regenerated.

`verify` compares a version only when its tag is reachable from `HEAD`, because that is the same scope the builder walks
(`git tag --merged`). A branch cut before the newest release cannot derive that version at all, so `verify` names it as
skipped and moves on instead of reporting drift that does not exist.

## Verify

`.github/workflows/ci.yml` runs on every pull request. `.github/scripts/ci_changes.py` picks the jobs from the changed
paths, and the required check `ci-ok` passes when every job passed or was skipped. To reproduce a job:

| Job | Command |
|---|---|
| Automation | See the `.automation/` commands above |
| Go | `cd core && CGO_ENABLED=0 go test . ./internal/logstore && CGO_ENABLED=0 go vet . ./internal/logstore`, plus the Android vet under Native Component Verification |
| Rust | `cargo test --locked --manifest-path services/helper/Cargo.toml` and `--manifest-path plugins/rust_api/rust/Cargo.toml` |
| Flutter | `flutter analyze --no-fatal-infos`, then `flutter test` |
| Android unit | `cd android && ./gradlew :common:testDebugUnitTest :service:testDebugUnitTest :app:testDebugUnitTest -Ptarget-platform=android-arm64` |
| Android compile | `flutter build apk --release --target-platform android-arm64` |

Run `flutter analyze --no-fatal-infos` before committing; CI fails on a warning or error.

CI leaves these to you. Run them when you touch their area:

- `bash tool/check_plugins.sh` analyzes and tests every package under `plugins/`. Root analysis excludes `plugins/**`, and
  root tests do not discover nested plugin packages.
- `bash tool/hooks/test.sh` runs every `*_test.sh` beside the git hook scripts.

## Worktree Tooling

```bash
bash tool/worktrees.sh list       # every worktree with owner tool and dirty/clean state
bash tool/worktrees.sh prune      # remove clean worktrees; add --force to drop dirty ones too
```
