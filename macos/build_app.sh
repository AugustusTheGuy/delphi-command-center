#!/bin/zsh
set -euo pipefail
ROOT="${DHC_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
APP="$ROOT/dist/Delphi Command Center.app"
MACOS="$APP/Contents/MacOS"
RES="$APP/Contents/Resources"
rm -rf "$APP"
mkdir -p "$MACOS" "$RES"
swiftc -O -o "$MACOS/DelphiCommandCenter" "$ROOT/macos/main.swift" -framework Cocoa -framework WebKit

ICONSET="$(mktemp -d)/delphi.iconset"
mkdir -p "$ICONSET"
SRC="$ROOT/assets/delphi_app_icon.png"
if [[ -f "$SRC" ]]; then
  RAW="$ICONSET/source.png"
  sips -s format png "$SRC" --out "$RAW" >/dev/null
  for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$RAW" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$RAW" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$RES/Delphi.icns" || true
fi

cat > "$APP/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Delphi Command Center</string>
  <key>CFBundleDisplayName</key><string>Delphi Command Center</string>
  <key>CFBundleIdentifier</key><string>com.delphitech.commandcenter</string>
  <key>CFBundleExecutable</key><string>DelphiCommandCenter</string>
  <key>CFBundleIconFile</key><string>Delphi</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSRemovableVolumesUsageDescription</key>
  <string>Delphi saves the library list on ExternalSSD when you allow it.</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key><true/>
  </dict>
</dict>
</plist>
EOF
chmod +x "$MACOS/DelphiCommandCenter"
mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/Delphi Command Center.app"
cp -R "$APP" "$HOME/Applications/Delphi Command Center.app"
echo "Built $APP"
