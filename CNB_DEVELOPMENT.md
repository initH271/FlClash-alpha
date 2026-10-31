# CNB cloud development

CNB runs no CI for this repository, so development checks happen on GitHub ([AUTOMATION.md](AUTOMATION.md)). For
development on CNB, use the cloud environment.

## Start

Open https://cnb.cool/507space/FlClash-alpha and press **FlClash 云开发**.

`.cnb.yml` (`vscode`) starts a 4-CPU WebIDE from `.cnb/Dockerfile`, with Flutter, Go, Rust and the Android SDK pinned there.
`.cnb/run.sh prepare` initializes the submodules and runs `flutter pub get`. Dependency directories use copy-on-write
caches. The image rebuilds when the Dockerfile changes.

## Deliver

Push the branch to GitHub and open a PR there. A branch pushed to CNB runs nothing.

The personal signing key stays on GitHub, so an APK built here cannot update the installed app.

## Cost

Allocated CPUs multiplied by elapsed time gives core-hours, and an idle WebIDE counts. Stop the environment after use.
