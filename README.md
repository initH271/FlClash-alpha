# FlClash-alpha

**English** · [简体中文](translations/README_zh_CN.md)

FlClash-alpha is an independently maintained fork of [chen08209/FlClash](https://github.com/chen08209/FlClash). It is not an official upstream distribution. Prebuilt packages target **Android ARM64** and follow upstream stable releases.

## How it differs from the official app

- **Persistent diagnostics:** logs are kept on disk across restarts and can be exported in one step for troubleshooting.
- **Dual-channel releases:** builds are published to both GitHub and CNB with a fixed signing key. The app checks both channels, verifies the package and signature, and updates in place.
- **Network-aware automation:** the proxy can pause and resume automatically depending on the network you are on.

## Download

| Channel | Source | Download |
| --- | --- | --- |
| GitHub | [FlClash-alpha](https://github.com/initH271/FlClash-alpha) | [Latest release](https://github.com/initH271/FlClash-alpha/releases/latest) |
| CNB | [FlClash-alpha](https://cnb.cool/507space/FlClash-alpha) | [Latest APK](https://cnb.cool/507space/FlClash-alpha/-/releases/latest/download/FlClash-alpha-arm64-v8a.apk) |

Both channels publish identical APK bytes signed with the same key. Releases include `SHA256SUMS.txt`.

## Install and upgrade

- The application ID is `com.follow.clash.dev`. It has a different identity from the official package, so the two cannot overwrite each other.
- Releases use a fixed signing key, so a new version installs over the old one and keeps your data.
- Install the APK manually the first time; after that, check for updates inside the app. Android will ask you to allow installing unknown apps.
- To migrate from the official app, use backup import and grant VPN and other system permissions again.

## Reporting issues

Open an issue on [GitHub Issues](https://github.com/initH271/FlClash-alpha/issues) using the bug form. Before pasting logs, remove subscription links, tokens, node addresses and other personal information.

## Development and maintenance

- [Log storage and retention](ROLLING_LOG_HISTORY.md)
- [Release channels and update mechanism](RELEASE_CHANNELS.md)
- [Upstream approval, NPC roles and build scheduling](AUTOMATION.md)
- [CNB development environment](CNB_DEVELOPMENT.md)
- [Build and test commands](.agents/commands.md)

GitHub builds and signs releases; CNB mirrors the same artifact. Signing keys and automation credentials are not committed.

## Attribution and license

Upstream: [chen08209/FlClash](https://github.com/chen08209/FlClash). Thanks to the original author, June2, Arue, and all upstream contributors. This fork is maintained by Aharon (initH271).

The project retains the **GNU General Public License v3 (GPL-3.0)**. See [LICENSE](LICENSE) for the complete terms. Use, modifications and redistribution must comply with the license and preserve required copyright and license notices. The software is provided without warranty as specified by the license.

## Intended use

This project is maintained for **learning and research** into networking, application development and build automation. It does not provide proxy nodes or subscription services. Follow applicable laws; **illegal use is prohibited, and the maintainer does not support unlawful activities**.

This purpose statement does not replace GPL-3.0 or restrict the rights granted by that license.
