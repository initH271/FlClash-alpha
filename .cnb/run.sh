#!/usr/bin/env bash
set -euo pipefail
mkdir -p dist
measure() {
  local name="$1" start end code
  shift
  start=$(date +%s)
  set +e
  "$@"
  code=$?
  set -e
  end=$(date +%s)
  printf '%s,%s,%s\n' "$name" "$((end-start))" "$code" | tee -a dist/timings.csv
  return "$code"
}
prepare() (
  set -e
  git submodule update --init --recursive
  flutter --version
  go version
  rustc --version
  java -version
  flutter pub get
)
check() (
  set -e
  (
    cd core
    CGO_ENABLED=0 go test -c -o /tmp/flclash-core-tests .
    install -d -o nobody -g nogroup /tmp/flclash-test-home
    runuser -u nobody -- env HOME=/tmp/flclash-test-home /tmp/flclash-core-tests -test.timeout=10m
    CGO_ENABLED=0 go test ./internal/logstore
    CGO_ENABLED=0 go vet . ./internal/logstore
  )
  flutter analyze --no-fatal-infos
  local backup
  backup=$(mktemp)
  cp pubspec.yaml "$backup"
  trap 'cp "$backup" pubspec.yaml; rm -f "$backup"' EXIT
  sed -i 's/build_assets: true/build_assets: false/g' pubspec.yaml
  if [ -f .automation/candidate.json ]; then
    flutter test --reporter expanded
  else
    flutter test test/common/app_update_test.dart test/common/log_history_test.dart test/core/protocol_contract_test.dart test/views/logs_view_test.dart --reporter expanded
  fi
)
build() (
  set -e
  mkdir -p "$HOME/.android"
  test -n "${KEYSTORE_BASE64:-}"
  printf '%s' "$KEYSTORE_BASE64" | base64 --decode > "$HOME/.android/debug.keystore"
  chmod 600 "$HOME/.android/debug.keystore"
  local build_number
  build_number=$(python3 -c "import json; print(json.load(open('.github/release.json'))['build'])")
  flutter build apk --release --target-platform android-arm64 --dart-define=APP_ENV=stable --build-number "$build_number"
  bash .github/scripts/sign-apk.sh build/app/outputs/flutter-apk/app-release.apk
  cp build/app/outputs/flutter-apk/app-release.apk dist/FlClash-alpha-arm64-v8a.apk
  python3 .github/scripts/prepare-release.py
)
case "${1:-all}" in
  prepare) measure prepare prepare ;;
  check) measure checks check ;;
  build) measure apk build ;;
  all) measure prepare prepare; measure checks check; measure apk build ;;
  *) echo 'Usage: run.sh prepare|check|build|all' >&2; exit 2 ;;
esac
