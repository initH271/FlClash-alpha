# FlClash-alpha releases and updates

Both repositories are public:
- https://github.com/initH271/FlClash-alpha
- https://cnb.cool/507space/FlClash-alpha

## Publishing

Merging a PR that changes `.github/release.json` and `.github/release-notes.md` releases: see
[AUTOMATION.md](AUTOMATION.md#releases). Increment the build for every release and never reuse a published one. Write each
user-facing commit's `Changelog:` trailer per [CHANGELOG_STYLE.md](CHANGELOG_STYLE.md).

GitHub Actions builds and tests Android ARM64, signs it with the personal key from Actions Secrets, verifies the pinned
certificate, and publishes a versioned Release with APK, SHA256SUMS.txt and update.json. The application ID
stays com.follow.clash.dev. The private key is not in either repository.

A separate run then builds Windows amd64 from the same commit and adds FlClash-alpha-windows-amd64-setup.exe,
FlClash-alpha-windows-amd64.zip and update-windows.json, with a line each in SHA256SUMS.txt. Those files can arrive some
time after the APK, and a failed Windows build leaves the Android release as it is: see
[AUTOMATION.md](AUTOMATION.md#windows-packages).

## Windows identity

The Windows package is a separate app from the official FlClash, as com.follow.clash.dev is on Android. Both can be
installed at once; running both at once is not supported, because TUN and the ports collide.

| | FlClash-alpha | Official FlClash |
|---|---|---|
| Inno `AppId` | `94491F5A-A742-4DFF-B144-119A92A2FFD1` | `728B3532-C74B-4870-9068-BE70FE12A3E6` |
| Install directory | `Program Files\FlClash-alpha` | `Program Files\FlClash` |
| Data directory | `%APPDATA%\com.follow.dev\clash` | `%APPDATA%\com.follow\clash` |
| Helper service | `FlClashAlphaHelperService` | `FlClashHelperService` |
| Start menu and desktop shortcut, `HKCU\...\Run` value, Apps and Features entry | `FlClash-alpha` | `FlClash` |

The installer only ends processes running from its own directory. The executables keep their names, and the application
and window titles stay `FlClash`, the same name the Android build shows. The URL schemes `clash`, `clashmeta` and
`flclash` are shared, as they are on Android: the app that started last answers them, and uninstalling removes them only
if they point at the app being removed. Installing or uninstalling also runs `--clear-stale-proxy`, which turns off a
system proxy the other app may have set.

## CNB mirror

CNB runs a one-CPU mirror job on pushes to its main, hourly at minute 7, when the release build starts it, and from the web
button. It uses CNB's temporary pipeline token, downloads the published GitHub APK, verifies the checksum and release
identity, uploads permanent CNB assets, and only then publishes the draft. Both hosts serve identical APK bytes. Existing
published versions are not overwritten, and older GitHub builds do not replace newer CNB ones. The release build moves CNB
main to the release commit before publishing.

Windows files never hold up the APK. Once the APK is published on CNB, including on a later run for a tag that is already
there, the job copies the Windows files of the latest GitHub Release that CNB lacks, checks each against SHA256SUMS.txt by
file name and update-windows.json against the installer's hash and the tag, and then uploads that SHA256SUMS.txt. It does
not check the signature, because the app does. A failure fails the job with the APK already out, and the next hourly run
tries again. It compares file sizes, so a complete release is not uploaded twice. It does nothing for a Release without
Windows files, or when CNB has a newer build. The job allows 20 minutes; the CNB OpenAPI schema states no limit on the
size of one asset.

## App updates

Android and Windows update inside the app. macOS and Linux do not check for updates.

On Android, startup/manual update checks fetch both public latest-release
update.json attachments in
parallel. The build number is compared with the installed Android build number.
Only personal com.follow.clash.dev ARM64 releases with valid metadata qualify.
The download endpoint is checked with HEAD. Among reachable updates, the newest
build wins; equal builds are ordered by metadata plus APK HEAD response latency.
Each metadata/probe operation has a six-second deadline. This measures response
latency, not sustained download bandwidth. One broken channel does not block the
other. The Android update dialog downloads the selected version-specific APK inside the app,
with progress, same-version cache reuse, and fallback to an identical mirror. SHA-256
and native package/version/signing-certificate checks gate the Install update button.
Android confirms installation; unknown-source authorization opens this app's settings
and resumes after permission is granted. The dialog shows the active channel.

On Windows the same checks, channel selection, dialog, progress, cache and mirror fallback apply, with these differences:

- The app reads update-windows.json from both latest-release attachments, and never update.json. A 404 means no update,
  because the Windows files reach a Release after the APK and can be missing for good when a build fails.
- The file holds `{"payload": "<base64 JSON>", "signature": "<base64>"}`. The installer runs as administrator and carries
  no code signature, so a hash in an unsigned file would hand a compromised mirror administrator access. The signature is
  RSASSA-PKCS1-v1_5 with SHA-256 over `FlClash-alpha-windows-update-v1\n` followed by the payload text, made in
  `Windows publish` with the APK signing key. The app carries that key's certificate, whose SHA-256 is the pinned
  certificateSha256, so a new signing key needs a new app build on both platforms.
- The app checks the signature, the application ID and the installer name, the build, and after downloading the SHA-256,
  which it checks again immediately before starting the installer. Any failure rules that source out and leaves the
  other one working.
- Install update starts the installer through UAC with `windowsInstallerArguments` from `lib/common/app_update.dart`.
  Declining UAC returns to the install button. The installer closes the app, replaces it and, because of `/RELAUNCH`,
  starts it again. It starts elevated, as the installer's own launch option does. Nothing installs without that click.

The packages have no Authenticode signature, so SmartScreen warns when a package is run by hand.

Older installed Android builds keep their existing updater. Install build 2026094004 once
manually to activate the in-app download and installation flow. Official FlClash packages and
signatures are incompatible with this personal .dev upgrade path.

The CNB OpenAPI host requires authentication even for this public repository, so the app uses cnb.cool public release
attachments; only CI uses api.cnb.cool.

To run the optional live endpoint test after disabling native hooks for tests:
`flutter test --dart-define=RUN_UPDATE_NETWORK_TESTS=true test/common/app_update_test.dart`
