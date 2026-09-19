# FlClash-alpha

**English** · [简体中文](README_zh_CN.md)

A personal FlClash fork maintained by **Aharon ([initH271 on GitHub](https://github.com/initH271), [Aharon on CNB](https://cnb.cool/u/Aharon))**, based on [chen08209/FlClash](https://github.com/chen08209/FlClash). It focuses on persistent diagnostic logs, app updates, and maintaining personal enhancements across upstream releases.

This is an independently maintained fork, not an official upstream distribution. Prebuilt packages currently target **Android ARM64**.

## Download and source

| Channel | Source | Download |
| --- | --- | --- |
| GitHub | [FlClash-alpha](https://github.com/initH271/FlClash-alpha) | [Latest release](https://github.com/initH271/FlClash-alpha/releases/latest) |
| CNB | [FlClash-alpha](https://cnb.cool/507space/FlClash-alpha) | [Latest APK](https://cnb.cool/507space/FlClash-alpha/-/releases/latest/download/FlClash-alpha-arm64-v8a.apk) |

Both channels publish identical APK bytes signed with the same personal key. Releases include `SHA256SUMS.txt`.

## Enhancements

- **Rolling log files:** core and APP logs each retain up to ten 5 MiB files across restarts. The live view keeps its 5,000-entry limit independently of disk history.
- **One complete export:** export all retained core logs, APP logs and a recent UI snapshot. Expired files and records from before installation cannot be recovered.
- **Two update channels:** check GitHub and CNB concurrently, prefer the newest build, then choose the faster reachable mirror for equal versions. Failed downloads can fall back to the other mirror.
- **In-app updates:** download with progress, verify the checksum, package, build and signing certificate, then tap Install update to open Android's confirmation screen.
- **Approved upstream tracking:** new stable upstream releases create decision Issues and NPC analysis. Owner approval gates integration, testing, builds and publication.

## Installation and upgrades

The application ID is `com.follow.clash.dev`. Builds use a fixed personal signing key, so subsequent releases can update the installed fork while preserving data. Its identity differs from the official upstream package.

Install an APK manually once when starting or upgrading from a version without the in-app installer. Afterwards, use About → Check for updates. Startup checks also download new releases when automatic update checks are enabled.

Android may ask you to allow this app to install unknown apps. Return after granting access and confirm installation in the system installer. The app does not bypass Android confirmation for silent installation. Closing the update window cancels an unfinished download; verified packages are cached for reuse.

The upstream backup format is retained. Migrate official-app settings through backup import and regrant system permissions such as VPN access. Export important logs before uninstalling or clearing application data.

## Development and maintenance

- [Log storage and retention](ROLLING_LOG_HISTORY.md)
- [Release channels and update mechanism](RELEASE_CHANNELS.md)
- [Upstream approval, NPC roles and build scheduling](AUTOMATION.md)
- [CNB development environment](CNB_DEVELOPMENT.md)
- [Build and test commands](.agents/commands.md)

GitHub is the primary build and signing platform; CNB mirrors the same artifact. Recovery prioritizes artifact reuse. Signing keys and automation credentials are not committed.

Report issues through [CNB Issues](https://cnb.cool/507space/FlClash-alpha/-/issues). Review and redact subscriptions, credentials and personal information before sharing logs.

## Attribution and license

Upstream: [chen08209/FlClash](https://github.com/chen08209/FlClash). Thanks to the original author, June2, Arue, and all upstream contributors. This fork's log, update and maintenance enhancements are maintained by Aharon (initH271).

The project retains the **GNU General Public License v3 (GPL-3.0)**. See [LICENSE](LICENSE) for the complete terms. Use, modifications and redistribution must comply with the license and preserve required copyright and license notices. The software is provided without warranty as specified by the license.

## Intended use

This project is maintained for **learning and research** into networking, application development and build automation. It does not provide proxy nodes or subscription services. Follow applicable laws; **illegal use is prohibited, and the maintainer does not support unlawful activities**.

This purpose statement does not replace GPL-3.0 or restrict the rights granted by that license.
