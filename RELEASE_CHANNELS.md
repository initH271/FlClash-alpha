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

A separate run then builds Windows amd64 from the same commit and adds FlClash-alpha-windows-amd64-setup.exe and
FlClash-alpha-windows-amd64.zip, with a line each in SHA256SUMS.txt. Those files can arrive some time after the APK, and
a failed Windows build leaves the Android release as it is: see [AUTOMATION.md](AUTOMATION.md#windows-packages).

## CNB mirror

CNB runs a one-CPU mirror job on pushes to its main, hourly at minute 7, when the release build starts it, and from the web
button. It uses CNB's temporary pipeline token, downloads the published GitHub APK, verifies the checksum and release
identity, uploads permanent CNB assets, and only then publishes the draft. Both hosts serve identical APK bytes. Existing
published versions are not overwritten, and older GitHub builds do not replace newer CNB ones. The release build moves CNB
main to the release commit before publishing.

Windows files never hold up the APK. Once the APK is published on CNB, including on a later run for a tag that is already
there, the job copies the Windows files of the latest GitHub Release that CNB lacks, checks each against SHA256SUMS.txt by
file name, and then uploads that SHA256SUMS.txt. A failure fails the job with the APK already out, and the next hourly run
tries again. It compares file sizes, so a complete release is not uploaded twice. It does nothing for a Release without
Windows files, or when CNB has a newer build. The job allows 20 minutes; the CNB OpenAPI schema states no limit on the
size of one asset.

## App updates

Windows has no in-app update: the updater only runs on Android, and update.json describes the APK. Download a new package
by hand. The packages are not code-signed, so SmartScreen warns on first run. The installer keeps upstream's `app_id` and
publisher, so installing it replaces an official FlClash Windows installation in place, with the same data directory, and
the official installer replaces it the same way.

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

Older installed builds keep their existing updater. Install build 2026094004 once
manually to activate the in-app download and installation flow. Official FlClash packages and
signatures are incompatible with this personal .dev upgrade path.

The CNB OpenAPI host requires authentication even for this public repository, so the app uses cnb.cool public release
attachments; only CI uses api.cnb.cool.

To run the optional live endpoint test after disabling native hooks for tests:
`flutter test --dart-define=RUN_UPDATE_NETWORK_TESTS=true test/common/app_update_test.dart`
