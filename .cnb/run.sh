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
case "${1:-prepare}" in
  prepare) measure prepare prepare ;;
  *) echo 'Usage: run.sh prepare' >&2; exit 2 ;;
esac
