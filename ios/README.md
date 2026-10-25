# Cumulous iOS (SwiftUI)

Native Cumulous app: **Home · Photos · Backups · Confirm**.

Photos render **inside the app** (cached thumbs + full media from your Mac Mini API), with deeper tags than Apple Photos.

## Open in Xcode

```bash
open ~/DelphiHomeController/ios/Cumulous.xcodeproj
```

1. Select your **Team** under Signing & Capabilities (free Apple ID works for device debug).
2. If Xcode says iOS platform missing: **Settings → Platforms** → download **iOS**.
3. Plug in iPhone → Run (▶).

Bundle ID: `llc.delphifintech.cumulous`

## Mac Mini connection

In-app **Settings** (or Home → Mac Mini Connection): set API base to  
`http://<Mac-LAN-IP>:8765`  
(default `http://192.168.1.100:8765`).

## Without Xcode (today)

Mac Cumulous → **Install on Phones** → **Push Cumulous app to connected iPhone**  
or Safari on phone: `http://<Mac-IP>:8765/install`  

- Install profile → **Home Screen** full-screen app shell (`/app/`) with Photos  
- Or choose **App Library** preference  
- Photos still load **in the Cumulous UI**, not as a bare URL page

## IPA for USB install

After archiving in Xcode, export and place:

`DelphiHomeController/dist/Cumulous.ipa`

Cumulous will try `ideviceinstaller` on USB invite.

## Project layout

```
ios/
  Cumulous.xcodeproj
  Cumulous/
    CumulousApp.swift
    Info.plist
    Theme/
    Services/CumulousAPI.swift
    Views/  (Home, Photos, Backups, Confirm, Settings)
    Assets.xcassets/
```
