#!/bin/bash
# Build Cumulous.app for Desktop + Dock with latest icon from repo assets.
set -euo pipefail

DHC="${DHC:-$HOME/DelphiHomeController}"
APP_DESKTOP="$HOME/Desktop/Cumulous.app"
APP_LOCAL="$HOME/Applications/Cumulous.app"
ICON_SRC="$DHC/cumulous/assets/icons/cumulous_mac_icon.png"
ICNS_SRC="$DHC/cumulous/assets/icons/Cumulous.icns"
LAUNCHER="$DHC/scripts/launch_cumulous.command"
VERSION_FILE="$DHC/cumulous/VERSION"

VERSION="0.1.0"
if [[ -f "$VERSION_FILE" ]]; then
  VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
fi

build_app() {
  local APP="$1"
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

  cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>CumulousLauncher</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>llc.delphifintech.cumulous</string>
  <key>CFBundleName</key>
  <string>Cumulous</string>
  <key>CFBundleDisplayName</key>
  <string>Cumulous</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>LSUIElement</key>
  <false/>
</dict>
</plist>
PLIST

  cat > "$APP/Contents/MacOS/CumulousLauncher" <<EOF
#!/bin/bash
# Always re-sync icon + version from source tree, then launch latest Cumulous
export DHC="$DHC"
if [[ -x "\$DHC/scripts/sync_cumulous_launcher.sh" ]]; then
  "\$DHC/scripts/sync_cumulous_launcher.sh" --quiet || true
fi
exec "\$DHC/scripts/launch_cumulous.command"
EOF
  chmod +x "$APP/Contents/MacOS/CumulousLauncher"

  if [[ -f "$ICNS_SRC" ]]; then
    cp "$ICNS_SRC" "$APP/Contents/Resources/AppIcon.icns"
  elif [[ -f "$ICON_SRC" ]]; then
    mkdir -p "$APP/Contents/Resources/AppIcon.iconset"
    sips -z 1024 1024 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_512x512@2x.png" >/dev/null
    sips -z 512 512 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_512x512.png" >/dev/null
    sips -z 256 256 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_256x256.png" >/dev/null
    sips -z 128 128 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_128x128.png" >/dev/null
    sips -z 64 64 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_32x32@2x.png" >/dev/null
    sips -z 32 32 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_32x32.png" >/dev/null
    sips -z 16 16 "$ICON_SRC" --out "$APP/Contents/Resources/AppIcon.iconset/icon_16x16.png" >/dev/null
    iconutil -c icns "$APP/Contents/Resources/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || true
    rm -rf "$APP/Contents/Resources/AppIcon.iconset"
  fi

  # Touch so Finder refreshes icon
  touch "$APP"
  echo "Created: $APP (v$VERSION)"
}

mkdir -p "$HOME/Applications"
build_app "$APP_DESKTOP"
build_app "$APP_LOCAL"

# Add to Dock (persistent) if not already present
python3 <<'PY'
import os, plistlib, subprocess, shutil
from pathlib import Path

app = Path.home() / "Desktop" / "Cumulous.app"
if not app.is_dir():
    app = Path.home() / "Applications" / "Cumulous.app"
app_url = app.resolve().as_uri() + "/"

# Prefer dockutil
if shutil.which("dockutil"):
    subprocess.run(["dockutil", "--remove", "Cumulous", "--no-restart"], check=False, capture_output=True)
    subprocess.run(["dockutil", "--add", str(app), "--replacing", "Cumulous"], check=False)
    subprocess.run(["killall", "Dock"], check=False)
    print("Dock: dockutil add", app)
else:
    # Best-effort: open once so Launch Services knows it; user Dock may need drag once
    # Also write a small helper that uses `defaults` array-add with file-label
    subprocess.run(["open", "-g", str(app)], check=False)
    # Use dockutil-free approach via `defaults` + plutil is fragile; document fallback
    print("Dock: opened app for Launch Services; run: dockutil --add", app)
    print("Or drag Cumulous from Desktop into the Dock.")
PY

# Refresh Finder icon cache for Desktop
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DESKTOP" 2>/dev/null || true

echo "Desktop: $APP_DESKTOP"
echo "Applications: $APP_LOCAL"
