#!/usr/bin/env bash
set -euo pipefail
apk="$1"
keystore="$HOME/.android/debug.keystore"
build_tools="$(find "$ANDROID_HOME/build-tools" -mindepth 1 -maxdepth 1 -type d | sort -V | tail -n 1)"
"$build_tools/apksigner" sign --ks "$keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android "$apk"
expected="$(keytool -exportcert -keystore "$keystore" -alias androiddebugkey -storepass android | sha256sum | cut -d ' ' -f 1)"
test "$expected" = '4cc5094e24f4a4cfde3a37d6c839ae376bd74c50075d8ee6bc73e25682e9afad'
actual="$("$build_tools/apksigner" verify --print-certs "$apk" | sed -n 's/^.*certificate SHA-256 digest: //p' | sort -u)"
echo "Expected certificate: $expected"
echo "APK certificate: $actual"
"$build_tools/apksigner" verify --print-certs "$apk"
test "$actual" = "$expected"
echo "Verified personal signing certificate: $actual"
python3 .automation/verify_apk.py "$apk" "$build_tools/aapt"
