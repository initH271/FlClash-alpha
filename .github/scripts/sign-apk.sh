#!/usr/bin/env bash
set -euo pipefail
apk="$1"
keystore="$HOME/.android/debug.keystore"
build_tools="$(find "$ANDROID_HOME/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -n 1)"
"$build_tools/apksigner" sign --ks "$keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android "$apk"
expected="$(keytool -exportcert -keystore "$keystore" -alias androiddebugkey -storepass android | sha256sum | cut -d ' ' -f 1)"
actual="$("$build_tools/apksigner" verify --print-certs "$apk" | sed -n 's/^Signer #1 certificate SHA-256 digest: //p')"
echo "Expected certificate: $expected"
echo "APK certificate: $actual"
"$build_tools/apksigner" verify --print-certs "$apk"
test "$actual" = "$expected"
echo "Verified personal signing certificate: $actual"
