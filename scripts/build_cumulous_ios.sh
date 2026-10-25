#!/usr/bin/env bash
# CTO-owned iOS build: universal app for iPhone 12+ (one binary — not per-model).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IOS="$ROOT/ios"
SCHEME="Cumulous"
PROJ="$IOS/Cumulous.xcodeproj"
DERIVED="${CUMULOUS_DERIVED:-$HOME/Library/Developer/Xcode/DerivedData/Cumulous-cli}"

echo "== Cumulous iOS build =="
echo "Project: $PROJ"

xcodebuild -scheme "$SCHEME" -project "$PROJ" \
  -destination 'platform=iOS Simulator,name=iPhone 16,OS=18.6' \
  -configuration Debug \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  build

APP="$DERIVED/Build/Products/Debug-iphonesimulator/Cumulous.app"
echo "App: $APP"
if command -v xcrun >/dev/null; then
  xcrun simctl boot "iPhone 16" 2>/dev/null || true
  xcrun simctl install booted "$APP" || true
  BID=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$APP/Info.plist" 2>/dev/null || true)
  if [[ -n "${BID:-}" ]]; then
    xcrun simctl launch booted "$BID" || true
    echo "Launched $BID"
  fi
fi
echo "BUILD OK"
