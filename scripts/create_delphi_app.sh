#!/bin/bash
# Build Delphi Command Center.app for Desktop/Dock
set -euo pipefail

DHC="$HOME/DelphiHomeController"
APP="$HOME/Desktop/Delphi Command Center.app"
ICON_SRC="$DHC/assets/delphi_app_icon.png"
LAUNCHER="$DHC/scripts/launch_delphi.command"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>DelphiLauncher</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>com.delphi.homecontrol</string>
  <key>CFBundleName</key>
  <string>Delphi Command Center</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/DelphiLauncher" <<EOF
#!/bin/bash
exec "$LAUNCHER"
EOF
chmod +x "$APP/Contents/MacOS/DelphiLauncher"

if [[ -f "$ICON_SRC" ]]; then
  mkdir -p "$APP/Contents/Resources/AppIcon.iconset"
  sips -z 1024 1024 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_512x512@2x.png" >/dev/null
  sips -z 512 512 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_512x512.png" >/dev/null
  sips -z 256 256 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_256x256.png" >/dev/null
  sips -z 128 128 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_128x128.png" >/dev/null
  iconutil -c icns "$APP/Contents/Resources/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || cp "$ICON_SRC" "$APP/Contents/Resources/AppIcon.png"
fi

echo "Created: $APP"
open -R "$APP"