# FlClash-alpha releases and updates

Both repositories are public:
- https://github.com/initH271/FlClash-alpha
- https://cnb.cool/507space/FlClash-alpha

GitHub Actions builds and tests Android ARM64, explicitly signs it with the
existing personal key from Actions Secrets, verifies the pinned certificate,
and publishes an immutable versioned Release with APK, SHA256SUMS.txt and
update.json. Increment `.github/release.json` build for every release and edit
`.github/release-notes.md` before pushing main. Never reuse a published build.
Application ID stays com.follow.clash.dev. The private key is not in either repo.

CNB runs a one-CPU mirror job on main pushes, manual triggers, and every 15
minutes. It uses CNB's temporary pipeline token, downloads the published GitHub
APK, verifies the checksum and release identity, uploads permanent CNB assets,
and only then publishes the draft. Both hosts serve identical APK bytes.
Existing published versions are not overwritten; newer CNB builds are not
replaced by older GitHub builds. Source commits must be pushed to both main
branches before release publication. The CNB cloud development environment is
preserved. Local CNB builds require KEYSTORE_BASE64; random benchmark signing
keys are no longer generated.

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

Verified release: alpha-0.8.97-2026094002 (2026-09-19). GitHub build
35451576550 and CNB mirror cnb-jkm-1k2t4m267 both succeeded. Anonymous manifest
GET and APK HEAD requests passed against both public hosts using the app's Dio
client. APK certificate and package ID were verified locally. The CNB OpenAPI
host requires authentication even for this public repository, so the app uses
cnb.cool public release attachments instead; CI alone uses api.cnb.cool.

To run the optional live endpoint test after disabling native hooks for tests:
`flutter test --dart-define=RUN_UPDATE_NETWORK_TESTS=true test/common/app_update_test.dart`

Build 2026094004 adds in-app Android download and installation. Local verification
passed 34 focused tests, including live public endpoint access, cache reuse,
corrupt-download fallback, cancellation cleanup, install-tap deduplication and
permission-return behavior. GitHub run 35457609580 completed the Android build
and publication. Both public channels served identical APK bytes. Package ID,
version code, fixed certificate, REQUEST_INSTALL_PACKAGES and the private update
FileProvider were verified in the APK. The real S24 installer interaction remains
to be exercised after the one-time bootstrap installation of this version.
