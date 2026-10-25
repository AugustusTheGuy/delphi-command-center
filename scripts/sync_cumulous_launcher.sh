#!/bin/bash
# Sync Cumulous.app icons + version from source on every launch (Desktop + ~/Applications).
set -euo pipefail
QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

DHC="${DHC:-$HOME/DelphiHomeController}"
ICON_SRC="$DHC/cumulous/assets/icons/cumulous_mac_icon.png"
ICNS_SRC="$DHC/cumulous/assets/icons/Cumulous.icns"
VERSION_FILE="$DHC/cumulous/VERSION"
VERSION="0.1.0"
[[ -f "$VERSION_FILE" ]] && VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"

sync_one() {
  local APP="$1"
  [[ -d "$APP" ]] || return 0
  local RES="$APP/Contents/Resources"
  local PLIST="$APP/Contents/Info.plist"
  mkdir -p "$RES"
  if [[ -f "$ICNS_SRC" ]]; then
    cp -f "$ICNS_SRC" "$RES/AppIcon.icns"
  elif [[ -f "$ICON_SRC" ]]; then
    sips -z 512 512 "$ICON_SRC" --out "$RES/AppIcon.png" >/dev/null 2>&1 || true
  fi
  if [[ -f "$PLIST" ]]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$PLIST" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$PLIST" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$PLIST" 2>/dev/null || true
  fi
  touch "$APP"
  [[ $QUIET -eq 1 ]] || echo "Synced icon/version → $APP ($VERSION)"
}

sync_one "$HOME/Desktop/Cumulous.app"
sync_one "$HOME/Applications/Cumulous.app"
