"""Invite Apple Account devices to install Cumulous (USB / Wi‑Fi / cellular).

Install surfaces:
  - In-app shell at /app (Photos + Home + Backups) — Web Clip / PWA full-screen.
  - Native SwiftUI project under ios/ (Xcode → device / IPA when signed).
  - USB: ideviceinstaller when dist/Cumulous.ipa exists.
  - New USB devices auto-get an install push (homescreen vs app-section preference).
"""

from __future__ import annotations

import json
import plistlib
import secrets
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from cumulous.paths import ensure_internal, internal_root
from cumulous.network_backup import backup_endpoints, local_ip_candidates, tailscale_ip


def invites_file() -> Path:
    return ensure_internal() / "install_invites.json"


def load_invites() -> dict:
    p = invites_file()
    if not p.exists():
        return {"invites": [], "responses": []}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"invites": [], "responses": []}


def save_invites(data: dict) -> None:
    ensure_internal()
    p = invites_file()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def app_shell_urls() -> list[str]:
    """In-app Cumulous UI (Photos inside the app, not bare address-only)."""
    urls: list[str] = []
    for h in local_ip_candidates():
        urls.append(f"http://{h}:8765/app/")
    ts = tailscale_ip()
    if ts:
        urls.append(f"http://{ts}:8765/app/")
    urls.append("http://127.0.0.1:8765/app/")
    return _dedupe(urls)


def portal_base_urls() -> list[str]:
    """URLs a phone can open for Cumulous install / home screen."""
    urls: list[str] = []
    for h in local_ip_candidates():
        urls.append(f"http://{h}:8765/install")
        urls.append(f"http://{h}:8765/app/")
        urls.append(f"http://{h}:8502")
    ts = tailscale_ip()
    if ts:
        urls.append(f"http://{ts}:8765/install")
        urls.append(f"http://{ts}:8765/app/")
        urls.append(f"http://{ts}:8502")
    urls.append("http://127.0.0.1:8765/install")
    urls.append("http://127.0.0.1:8765/app/")
    return _dedupe(urls)


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def best_portal_url() -> str:
    urls = portal_base_urls()
    for u in urls:
        if "127.0.0.1" not in u and ":8765/install" in u:
            return u
    return urls[0] if urls else "http://127.0.0.1:8765/install"


def best_app_url() -> str:
    """Full-screen app shell (Photos in-app) — preferred Web Clip target."""
    for u in app_shell_urls():
        if "127.0.0.1" not in u:
            return u
    return app_shell_urls()[0] if app_shell_urls() else "http://127.0.0.1:8765/app/"


def install_prefs_path() -> Path:
    return ensure_internal() / "device_install_prefs.json"


def load_install_prefs() -> dict:
    p = install_prefs_path()
    if not p.exists():
        return {"devices": {}, "default_preference": "homescreen"}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"devices": {}, "default_preference": "homescreen"}


def save_install_prefs(data: dict) -> None:
    ensure_internal()
    p = install_prefs_path()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def set_device_install_preference(device_id: str, preference: str) -> dict:
    """preference: homescreen | app_section | declined"""
    pref = (preference or "homescreen").strip().lower()
    if pref not in ("homescreen", "app_section", "declined"):
        pref = "homescreen"
    data = load_install_prefs()
    devices = data.setdefault("devices", {})
    devices[device_id] = {
        "preference": pref,
        "updated_at": time.time(),
    }
    save_install_prefs(data)
    return devices[device_id]


def get_device_install_preference(device_id: str) -> str:
    data = load_install_prefs()
    rec = (data.get("devices") or {}).get(device_id) or {}
    return rec.get("preference") or data.get("default_preference") or "homescreen"


def find_ipa() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "dist" / "Cumulous.ipa",
        root / "ios" / "dist" / "Cumulous.ipa",
        root / "Cumulous.ipa",
    ]
    for c in candidates:
        if c.is_file() and c.stat().st_size > 1000:
            return c
    return None


def try_usb_install_ipa(udid: str | None = None) -> dict[str, Any]:
    """Attempt ideviceinstaller when a signed IPA is present."""
    ipa = find_ipa()
    if not ipa:
        return {
            "ok": False,
            "action": "no_ipa",
            "message": (
                "No signed Cumulous.ipa yet. Using Web Clip profile / Safari install page instead. "
                "Build with Xcode when ready, place at dist/Cumulous.ipa."
            ),
        }
    import shutil

    tool = shutil.which("ideviceinstaller")
    if not tool:
        return {"ok": False, "action": "missing_tool", "message": "ideviceinstaller not found"}
    cmd = [tool, "install", str(ipa)]
    if udid:
        cmd = [tool, "-u", udid, "install", str(ipa)]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        ok = cp.returncode == 0
        return {
            "ok": ok,
            "action": "usb_ipa",
            "message": (cp.stdout or cp.stderr or "")[:400] or ("Installed" if ok else "Install failed"),
            "ipa": str(ipa),
        }
    except Exception as e:
        return {"ok": False, "action": "usb_error", "message": str(e)[:200]}


def try_usb_install_webclip(udid: str | None = None) -> dict[str, Any]:
    """Push Cumulous Home Screen webclip over USB via MobileConfig service.

    Unsupervised iPhones often reject silent webclip install (MDM required).
    On success / accept-pending, user still confirms in Settings if prompted.
    Always falls back to Safari install URL when USB profile is blocked.
    """
    profile = write_webclip_profile()
    if not profile.is_file() or profile.stat().st_size < 100:
        return {"ok": False, "action": "no_profile", "message": "Webclip profile missing"}

    data = profile.read_bytes()
    try:
        import asyncio

        async def _install() -> dict[str, Any]:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService

            lockdown = await create_using_usbmux(serial=udid) if udid else await create_using_usbmux()
            service = MobileConfigService(lockdown=lockdown)
            try:
                await service.install_profile(data)
            except Exception as e:
                msg = str(e)
                low = msg.lower()
                if "not permitted" in low or "webclip" in low or "4022" in msg:
                    return {
                        "ok": False,
                        "action": "webclip_requires_safari",
                        "message": (
                            "Apple blocks silent Home Screen install over USB without MDM. "
                            "Use Safari on the iPhone → install page."
                        ),
                        "profile": str(profile),
                        "install_via": "safari",
                        "detail": msg[:240],
                    }
                return {
                    "ok": False,
                    "action": "usb_webclip_failed",
                    "message": msg[:280] or "USB profile install failed — unlock and Trust the computer.",
                    "profile": str(profile),
                }
            # Confirm Cumulous appears, or treat as pending user confirm
            names: list[str] = []
            try:
                listed = await service.get_profile_list()
                meta = (listed or {}).get("ProfileMetadata") or {}
                for rec in meta.values():
                    names.append(str(rec.get("PayloadDisplayName") or ""))
            except Exception:
                pass
            if any("cumulous" in n.lower() for n in names):
                return {
                    "ok": True,
                    "action": "usb_webclip_installed",
                    "message": "Cumulous Home Screen profile is on the iPhone.",
                    "profile": str(profile),
                    "profiles": names,
                }
            return {
                "ok": True,
                "action": "usb_webclip_pending",
                "message": (
                    "Profile sent over USB. On the iPhone check Settings for "
                    "“Profile Downloaded” (or open Safari install page if nothing appears)."
                ),
                "profile": str(profile),
                "profiles": names,
            }

        return asyncio.run(_install())
    except ImportError:
        return {
            "ok": False,
            "action": "missing_pymobiledevice3",
            "message": "USB profile tool not ready; open install URL on the phone instead.",
            "profile": str(profile),
        }
    except Exception as e:
        msg = str(e)
        if "not connected" in msg.lower() or "no device" in msg.lower():
            return {"ok": False, "action": "no_usb_device", "message": "iPhone not visible on USB", "profile": str(profile)}
        return {"ok": False, "action": "usb_webclip_error", "message": msg[:200], "profile": str(profile)}


def push_install_to_usb_device(*, force: bool = True, wait_sec: float = 0) -> dict[str, Any]:
    """Push Cumulous install to the USB-connected iPhone (invite + profile + live push).

    If *wait_sec* > 0, wait up to that many seconds for a device to appear on usbmux.
    """
    from cumulous.devices import probe_connected_device
    from cumulous.apple_accounts import list_accounts

    deadline = time.time() + max(0.0, float(wait_sec))
    probe = probe_connected_device()
    while (not probe or not (probe.get("udid") or probe.get("imei"))) and time.time() < deadline:
        time.sleep(1.0)
        probe = probe_connected_device()

    if not probe or not (probe.get("udid") or probe.get("imei")):
        install_url = best_portal_url()
        return {
            "ok": False,
            "error": "no_usb_device",
            "message": (
                "No iPhone on USB. Plug in ROB IPHONE, unlock, tap Trust, then push again. "
                f"Or open Safari on the phone: {install_url}"
            ),
            "install_url": install_url,
        }

    device_id = str(probe.get("imei") or probe.get("udid") or probe.get("device_id"))
    name = probe.get("display_name") or "iPhone"
    udid = probe.get("udid")
    aid = ""
    for a in list_accounts():
        if a.get("is_ceo") or a.get("apple_id"):
            aid = a.get("apple_id") or ""
            if a.get("is_ceo"):
                break

    # 1) Webclip profile over USB (install prompt on phone)
    usb_profile = try_usb_install_webclip(udid)
    # 2) IPA if present
    usb_ipa = try_usb_install_ipa(udid)
    # 3) Invite + live poll push + Mac notify
    invite = create_invite_for_device(
        device_id=device_id,
        display_name=name,
        apple_account_id=aid,
        transport="usb",
        force=force,
        notify_macos=True,
    )
    # 4) Live install queue for /app shell
    try:
        from cumulous.app_update import package_version

        ver = package_version()
    except Exception:
        ver = "latest"
    install_url = best_portal_url()
    app_url = best_app_url()
    push = queue_install_push(
        device_ids=[device_id],
        install_url=install_url,
        app_url=app_url,
        version=ver,
        title=f"Install Cumulous v{ver}",
        body=(
            f"Cumulous v{ver} for {name}. "
            f"If a profile prompt appeared, tap Install. "
            f"Otherwise open Safari → {install_url}"
        ),
    )

    ok = bool(usb_profile.get("ok") or usb_ipa.get("ok") or invite.get("ok"))
    return {
        "ok": ok,
        "device": {
            "device_id": device_id,
            "display_name": name,
            "udid": udid,
            "transport": "usb",
        },
        "usb_webclip": usb_profile,
        "usb_ipa": usb_ipa,
        "invite": invite,
        "push": push,
        "install_url": install_url,
        "app_url": app_url,
        "profile_url": f"http://{(install_url.split('//',1)[-1].split('/')[0])}/install/webclip.mobileconfig",
        "message": (
            f"Install push to {name} over USB. "
            + (
                "Confirm Install on the iPhone for the Home Screen profile. "
                if usb_profile.get("ok")
                else f"Open Safari on the phone: {install_url} "
            )
            + "Photos open inside Cumulous after install."
        ),
    }


def build_webclip_mobileconfig(*, portal_url: str | None = None, display_name: str = "Cumulous") -> bytes:
    """Apple configuration profile: Web Clip on Home Screen → in-app shell (/app)."""
    payload_uuid = str(uuid.uuid4()).upper()
    profile_uuid = str(uuid.uuid4()).upper()
    icon_path = Path(__file__).resolve().parent / "assets" / "icons" / "AppIcon-1024.png"
    if not icon_path.is_file():
        icon_path = Path(__file__).resolve().parent / "assets" / "icons" / "cumulous_ios_icon.png"
    icon_data = icon_path.read_bytes() if icon_path.is_file() else None
    # Full-screen app shell with Photos inside Cumulous (not bare install page)
    url = portal_url or best_app_url()
    # Cache-bust so reinstall/update picks latest shell
    try:
        from cumulous.app_update import package_version

        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}v={package_version()}"
    except Exception:
        pass

    webclip: dict[str, Any] = {
        "PayloadType": "com.apple.webClip.managed",
        "PayloadVersion": 1,
        "PayloadIdentifier": f"llc.delphifintech.cumulous.webclip.{payload_uuid}",
        "PayloadUUID": payload_uuid,
        "PayloadDisplayName": display_name,
        "PayloadDescription": "Cumulous by Delphi Technologies — Photos + backup (full screen)",
        "URL": url,
        "Label": display_name,
        "IsRemovable": True,
        "FullScreen": True,
        "IgnoreManifestScope": True,
        "Precomposed": True,
    }
    if icon_data:
        webclip["Icon"] = icon_data

    profile = {
        "PayloadContent": [webclip],
        "PayloadDisplayName": "Cumulous Home Screen",
        "PayloadIdentifier": f"llc.delphifintech.cumulous.profile.{profile_uuid}",
        "PayloadRemovalDisallowed": False,
        "PayloadType": "Configuration",
        "PayloadUUID": profile_uuid,
        "PayloadVersion": 1,
        "PayloadDescription": "Adds Cumulous to your Home Screen. You can remove it anytime.",
        "PayloadOrganization": "Delphi FinTech LLC",
    }
    return plistlib.dumps(profile, fmt=plistlib.FMT_XML)


def write_webclip_profile() -> Path:
    ensure_internal()
    url = best_app_url()
    data = build_webclip_mobileconfig(portal_url=url)
    path = internal_root() / "Cumulous-HomeScreen.mobileconfig"
    path.write_bytes(data)
    try:
        path.chmod(0o644)
    except OSError:
        pass
    # also serve-friendly copy next to assets
    pub = Path(__file__).resolve().parent / "assets" / "Cumulous-HomeScreen.mobileconfig"
    try:
        pub.write_bytes(data)
    except OSError:
        pass
    return path


def pending_installs_path() -> Path:
    return ensure_internal() / "pending_install_pushes.json"


def load_pending_installs() -> dict[str, Any]:
    p = pending_installs_path()
    if not p.exists():
        return {"active": [], "updated_at": 0}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"active": [], "updated_at": 0}


def save_pending_installs(data: dict[str, Any]) -> None:
    ensure_internal()
    data["updated_at"] = time.time()
    p = pending_installs_path()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def prune_pending_installs(*, now: float | None = None) -> dict[str, Any]:
    now = now if now is not None else time.time()
    data = load_pending_installs()
    data["active"] = [
        a
        for a in (data.get("active") or [])
        if float(a.get("expires_at") or 0) > now and not a.get("acked")
    ]
    save_pending_installs(data)
    return data


def queue_install_push(
    *,
    device_ids: list[str] | None = None,
    install_url: str = "",
    app_url: str = "",
    version: str = "",
    title: str = "Install Cumulous",
    body: str = "",
    expires_sec: float = 72 * 3600,
) -> dict[str, Any]:
    """Queue a live install push for phones (polled by /app + /install/live)."""
    try:
        from cumulous.app_update import package_version

        ver = version or package_version()
    except Exception:
        ver = version or "latest"
    url = install_url or best_portal_url()
    app = app_url or best_app_url()
    now = time.time()
    push_id = secrets.token_hex(8)
    ids = list(device_ids or [])
    if not ids:
        try:
            from cumulous.devices import load_devices

            for d in load_devices().get("devices") or []:
                did = d.get("device_id") or ""
                if did and "mac-mini" not in did:
                    ids.append(did)
        except Exception:
            pass
    payload = {
        "push_id": push_id,
        "kind": "install",
        "title": title,
        "body": body
        or (
            f"Cumulous v{ver} is ready. Tap to open the install screen "
            f"and add it to your Home Screen."
        ),
        "install_url": url,
        "app_url": app,
        "profile_url": f"{url.rstrip('/').rsplit('/install', 1)[0]}/install/webclip.mobileconfig"
        if "/install" in url
        else "/install/webclip.mobileconfig",
        "version": ver,
        "device_ids": ids,
        "created_at": now,
        "expires_at": now + float(expires_sec),
        "acked": False,
        "open_path": "/install",
    }
    data = prune_pending_installs(now=now)
    # Replace prior install pushes so only latest shows
    data["active"] = [a for a in (data.get("active") or []) if a.get("kind") != "install"]
    data.setdefault("active", []).append(payload)
    save_pending_installs(data)
    return payload


def active_install_pushes_for_device(device_id: str = "", *, now: float | None = None) -> list[dict[str, Any]]:
    now = now if now is not None else time.time()
    data = prune_pending_installs(now=now)
    did = (device_id or "").strip()
    out: list[dict[str, Any]] = []
    for a in data.get("active") or []:
        if a.get("acked"):
            continue
        if float(a.get("expires_at") or 0) <= now:
            continue
        targets = a.get("device_ids") or []
        if not did or not targets or did in targets or any(
            did and (did in str(t) or str(t) in did) for t in targets
        ):
            out.append(
                {
                    "push_id": a.get("push_id"),
                    "kind": a.get("kind") or "install",
                    "title": a.get("title"),
                    "body": a.get("body"),
                    "install_url": a.get("install_url"),
                    "app_url": a.get("app_url"),
                    "profile_url": a.get("profile_url"),
                    "version": a.get("version"),
                    "open_path": a.get("open_path") or "/install",
                    "seconds_left": max(0, int(float(a.get("expires_at") or 0) - now)),
                }
            )
    return out


def ack_install_push(push_id: str) -> dict[str, Any]:
    data = load_pending_installs()
    for a in data.get("active") or []:
        if a.get("push_id") == push_id:
            a["acked"] = True
            a["acked_at"] = time.time()
    save_pending_installs(data)
    return {"ok": True, "push_id": push_id}


def push_install_prompt_macos(device_label: str, url: str, *, version: str = "") -> bool:
    try:
        safe = device_label.replace('"', "'")
        ver = (version or "").strip()
        ver_bit = f" v{ver}" if ver else ""
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "Install Cumulous{ver_bit} on {safe} — open install screen." '
                f'with title "Cumulous Install" sound name "Glass"',
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
        # Open install page on Mac so URL/QR is one click away
        try:
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        subprocess.Popen(
            [
                "osascript",
                "-e",
                f'display dialog "Install Cumulous{ver_bit} on {safe}\\n\\n'
                f"On the iPhone (Safari):\\n{url}\\n\\n"
                f'1) Tap “Add to Home Screen (profile)”\\n'
                f"2) Allow → Install Profile in Settings\\n"
                f'3) Open the Cumulous icon — Photos load inside the app." '
                f'with title "Cumulous · Install" buttons {{"Later", "Open Install Page"}} '
                f'default button "Open Install Page"',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def push_install_to_all_devices(*, force: bool = True, apple_account_id: str = "") -> dict[str, Any]:
    """Create invites + live install push for every registered iPhone; notify Mac."""
    try:
        from cumulous.app_update import package_version

        ver = package_version()
    except Exception:
        ver = "latest"
    write_webclip_profile()
    install_url = best_portal_url()
    app_url = best_app_url()

    results: list[dict[str, Any]] = []
    device_ids: list[str] = []
    try:
        from cumulous.devices import load_devices
        from cumulous.apple_accounts import list_accounts

        aid = (apple_account_id or "").strip().lower()
        if not aid:
            for a in list_accounts():
                if a.get("is_ceo"):
                    aid = (a.get("apple_id") or "").lower()
                    break
            if not aid:
                accs = list_accounts()
                if accs:
                    aid = (accs[0].get("apple_id") or "").lower()

        for d in load_devices().get("devices") or []:
            did = d.get("device_id") or ""
            if not did or "mac-mini" in did:
                continue
            da = (d.get("apple_account_id") or d.get("owner_username") or "").lower()
            if aid and da and da != aid and not d.get("is_ceo_override"):
                # still include CEO-linked devices; skip unrelated accounts only when filter set
                if apple_account_id and da != aid:
                    continue
            device_ids.append(did)
            results.append(
                create_invite_for_device(
                    device_id=did,
                    display_name=d.get("display_name") or did,
                    apple_account_id=aid or da,
                    transport="auto",
                    force=force,
                    notify_macos=False,
                )
            )
    except Exception as e:
        results.append({"ok": False, "error": str(e)[:160]})

    # Always include currently connected USB phone even if not in registry
    try:
        connected = auto_invite_connected_device(force=force)
        if connected.get("ok") and connected.get("invite"):
            inv = connected["invite"]
            did = inv.get("device_id")
            if did and did not in device_ids:
                device_ids.append(did)
            results.append(connected)
    except Exception:
        pass

    push = queue_install_push(
        device_ids=device_ids,
        install_url=install_url,
        app_url=app_url,
        version=ver,
        title=f"Install Cumulous v{ver}",
        body=(
            f"Cumulous v{ver} by Delphi Technologies is ready. "
            f"Tap to open the install screen, add the Home Screen icon, "
            f"and open Photos inside the app."
        ),
    )
    labels = ", ".join(
        (r.get("invite") or {}).get("display_name")
        or r.get("message")
        or "device"
        for r in results[:4]
    ) or "your iPhone"
    push_install_prompt_macos(labels[:80], install_url, version=ver)

    log = ensure_internal() / "push_log.jsonl"
    with log.open("a") as f:
        f.write(
            json.dumps(
                {
                    "ts": time.time(),
                    "type": "install_push_all",
                    "push_id": push.get("push_id"),
                    "version": ver,
                    "install_url": install_url,
                    "device_ids": device_ids,
                    "result_count": len(results),
                }
            )
            + "\n"
        )

    return {
        "ok": True,
        "version": ver,
        "install_url": install_url,
        "app_url": app_url,
        "profile_url": f"http://{install_url.split('//',1)[-1].split('/')[0]}/install/webclip.mobileconfig"
        if "://" in install_url
        else "/install/webclip.mobileconfig",
        "push": push,
        "device_ids": device_ids,
        "invites": results,
        "message": (
            f"Install push sent for Cumulous v{ver}. "
            f"Open on phone: {install_url}"
        ),
    }


def create_invite_for_device(
    *,
    device_id: str,
    display_name: str,
    apple_account_id: str,
    transport: str = "auto",
    preference: str | None = None,
    force: bool = False,
    notify_macos: bool = True,
) -> dict[str, Any]:
    """Create invite + push; user chooses Home Screen vs App Library / declines."""
    # Skip if already accepted recently (unless force)
    if not force:
        data0 = load_invites()
        for inv in reversed(data0.get("invites") or []):
            if inv.get("device_id") == device_id and inv.get("status") == "accepted":
                if time.time() - float(inv.get("responded_at") or inv.get("created_at") or 0) < 86400 * 30:
                    return {
                        "ok": True,
                        "skipped": True,
                        "reason": "already_accepted",
                        "invite": inv,
                        "message": f"{display_name} already has Cumulous installed (preference saved).",
                    }
            if inv.get("device_id") == device_id and inv.get("status") == "pending":
                if time.time() - float(inv.get("created_at") or 0) < 3600:
                    return {
                        "ok": True,
                        "skipped": True,
                        "reason": "pending_recent",
                        "invite": inv,
                        "message": f"Invite already pending for {display_name}.",
                    }

    pref = preference or get_device_install_preference(device_id)
    app_url = best_app_url()
    install_url = best_portal_url()
    profile = write_webclip_profile()
    invite_id = secrets.token_hex(8)
    # profile URL always on API host
    lan = next((h for h in local_ip_candidates() if not h.startswith("192.168.234.")), None)
    host = lan or "127.0.0.1"
    profile_url = f"http://{host}:8765/install/webclip.mobileconfig"
    try:
        from cumulous.app_update import package_version

        ver = package_version()
    except Exception:
        ver = ""
    rec = {
        "invite_id": invite_id,
        "device_id": device_id,
        "display_name": display_name,
        "apple_account_id": apple_account_id,
        "app_url": app_url,
        "portal_url": install_url,
        "profile_path": str(profile),
        "profile_url": profile_url,
        "preference": pref,  # homescreen | app_section
        "status": "pending",
        "created_at": time.time(),
        "transport": transport,
        "version": ver,
        "question": (
            f"Install Cumulous{(' v' + ver) if ver else ''} on “{display_name}”? "
            f"Home Screen icon or App Library — your choice."
        ),
        "swiftui_project": "ios/Cumulous.xcodeproj",
    }
    data = load_invites()
    data.setdefault("invites", []).append(rec)
    save_invites(data)

    if notify_macos:
        push_install_prompt_macos(display_name, install_url, version=ver)
    log = ensure_internal() / "push_log.jsonl"
    with log.open("a") as f:
        f.write(
            json.dumps(
                {
                    "ts": time.time(),
                    "type": "install_invite",
                    "device_id": device_id,
                    "invite_id": invite_id,
                    "status": "queued",
                    "preference": pref,
                    "channel": "local_notify_or_apns",
                    "app_url": app_url,
                }
            )
            + "\n"
        )

    usb_ipa = None
    usb_webclip = None
    if transport in ("auto", "usb"):
        from cumulous.devices import probe_connected_device

        probe = probe_connected_device()
        if probe and (
            probe.get("udid") == device_id
            or probe.get("imei") == device_id
            or probe.get("device_id") == device_id
            or (probe.get("display_name") or "").upper() in (display_name or "").upper()
        ):
            usb_webclip = try_usb_install_webclip(probe.get("udid"))
            usb_ipa = try_usb_install_ipa(probe.get("udid"))

    return {
        "ok": True,
        "invite": rec,
        "usb_install": usb_ipa,
        "usb_webclip": usb_webclip,
        "app_url": app_url,
        "install_url": install_url,
        "profile_url": profile_url,
        "message": (
            f"Install push sent for {display_name}. "
            + (
                "Confirm the profile Install prompt on the iPhone. "
                if (usb_webclip or {}).get("ok")
                else f"Open {install_url} on the phone → Home Screen or App Library → "
            )
            + f"Photos open inside Cumulous at {app_url}."
        ),
    }


def auto_invite_connected_device(*, force: bool = False) -> dict[str, Any]:
    """When a phone appears on USB, push Cumulous install (if not already handled)."""
    return push_install_to_usb_device(force=force, wait_sec=0)


def invite_all_apple_account_devices(apple_account_id: str) -> dict[str, Any]:
    """Ask every registered device under this Apple Account (user chooses per device)."""
    from cumulous.devices import load_devices

    aid = (apple_account_id or "").strip().lower()
    results = []
    for d in load_devices().get("devices") or []:
        da = (d.get("apple_account_id") or d.get("owner_username") or "").lower()
        if aid and da != aid:
            continue
        if d.get("device_id") in ("mac-mini-cumulous", "mac-mini-local"):
            continue  # Mac already has Cumulous
        results.append(
            create_invite_for_device(
                device_id=d["device_id"],
                display_name=d.get("display_name") or d["device_id"],
                apple_account_id=aid or da,
                transport="auto",
            )
        )
    return {"ok": True, "count": len(results), "results": results}


def record_response(
    invite_id: str,
    *,
    accepted: bool,
    device_id: str = "",
    preference: str = "",
    version: str = "",
) -> dict:
    data = load_invites()
    pref = (preference or "").strip().lower()
    if accepted and pref not in ("homescreen", "app_section"):
        pref = "homescreen"
    if not accepted:
        pref = pref or "declined"
    matched_name = ""
    matched_did = device_id
    for inv in data.get("invites") or []:
        if inv.get("invite_id") == invite_id or (not invite_id and device_id and inv.get("device_id") == device_id):
            inv["status"] = "accepted" if accepted else "declined"
            inv["responded_at"] = time.time()
            if device_id:
                inv["response_device_id"] = device_id
            if pref:
                inv["preference"] = pref
            did = device_id or inv.get("device_id") or ""
            matched_did = did
            matched_name = inv.get("display_name") or ""
            if did:
                set_device_install_preference(did, pref if accepted else "declined")
            break
    data.setdefault("responses", []).append(
        {
            "invite_id": invite_id,
            "accepted": accepted,
            "preference": pref,
            "ts": time.time(),
            "device_id": device_id,
        }
    )
    save_invites(data)
    if accepted and matched_did:
        try:
            from cumulous.app_update import package_version, record_device_install

            record_device_install(
                device_id=matched_did,
                version=version or package_version(),
                platform="ios",
                source=f"install_{pref or 'homescreen'}",
                display_name=matched_name,
                preference=pref,
            )
        except Exception:
            pass
    return {"ok": True, "accepted": accepted, "preference": pref, "device_id": matched_did}


def photo_mirror_status_report() -> dict[str, Any]:
    """Plain-language photo hosting / display status for CEO."""
    from cumulous.photo_offload import library_status, load_prefs

    lib = library_status()
    prefs = load_prefs()
    return {
        "host_originals_on_hdd": True,
        "host_originals_on_nextcloud": True,
        "hdd_library": lib.get("root"),
        "hdd_file_count": lib.get("file_count"),
        "dual_mirrored": lib.get("mirrored_dual_count"),
        "deletion_queue_pending": lib.get("deletion_queue_pending"),
        "free_phone_after_backup": bool(prefs.get("free_phone_storage_after_backup")),
        "require_dual_mirror_before_delete": bool(prefs.get("require_dual_mirror_before_delete", True)),
        "display": {
            "apple_photos_app_native_icloud_style": {
                "possible": False,
                "reason": (
                    "Apple does not allow third-party apps to show Mac-HDD photos inside "
                    "the system Photos app as iCloud-style placeholders."
                ),
            },
            "nextcloud_app": {
                "possible": True,
                "preferred": True,
                # Phone/app must use HTTPS (plain :8080 is blocked as "not secure")
                "url": "https://192.168.1.100:8443",
                "mac_browser_url": "https://127.0.0.1:8443",
                "require_https": True,
                "note": (
                    "View on phone without keeping full originals locally — "
                    "Nextcloud streams from this Mac Mini over HTTPS only. "
                    "Server: https://…:8443 — accept the home self-signed cert once."
                ),
            },
            "cumulous_photos_clone": {
                "possible": True,
                "preferred": True,
                "note": (
                    "In-app Photos.app-like library on Mac + iOS. "
                    "Deeper tagging (date, place, people, plants, objects, setting, context). "
                    "Persistently updated from dual-mirror backup; viewable on all devices."
                ),
            },
            "cumulous_app_gallery": {
                "possible": True,
                "preferred": True,
                "note": "Same as Cumulous Photos — library + deletion-queue API to free phone space.",
            },
        },
        "setup_choice": (
            "Free iPhone space only after BOTH HDD and Nextcloud copies verify. "
            "Then phone displays via Nextcloud/Cumulous without storing full originals."
        ),
    }
