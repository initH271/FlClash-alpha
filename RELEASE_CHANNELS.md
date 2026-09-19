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
other. Clicking Download opens the selected version-specific APK URL; Android
still asks before installation. The dialog includes the selected channel.

Old installed builds still use the upstream updater. Install this release once
manually to activate the dual-channel checker. Official FlClash packages and
signatures are incompatible with this personal .dev upgrade path.
