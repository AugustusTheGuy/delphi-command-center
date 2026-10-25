"""Live delivery of 4-digit challenge codes to all fan-out devices.

Channels:
  - Mac Mini: notification + Apple-style dialog (code + map)
  - All registered Apple devices: pending-code store polled by Cumulous iOS / web shell
  - Account-wide broadcast so any device on the Apple Account receives the code
  - push_log.jsonl for audit (never long-term cleartext after expiry prune)

Root cause of "only Mac gets codes": iOS must poll /challenge/live; fan-out
must include IMEI+UDID+device_id for every registered phone, and live endpoint
must return codes for any device on the same Apple Account.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal


def pending_codes_path() -> Path:
    return ensure_internal() / "pending_device_codes.json"


def load_pending() -> dict[str, Any]:
    p = pending_codes_path()
    if not p.exists():
        return {"active": [], "updated_at": 0}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"active": [], "updated_at": 0}


def save_pending(data: dict[str, Any]) -> None:
    ensure_internal()
    data["updated_at"] = time.time()
    p = pending_codes_path()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def prune_expired(data: dict[str, Any] | None = None, *, now: float | None = None) -> dict[str, Any]:
    now = now if now is not None else time.time()
    data = data or load_pending()
    active = [
        a
        for a in (data.get("active") or [])
        if float(a.get("expires_at") or 0) > now and not a.get("consumed")
    ]
    data["active"] = active
    save_pending(data)
    return data


def _device_label(device_id: str) -> str:
    try:
        from cumulous.devices import load_devices

        for d in load_devices().get("devices") or []:
            if d.get("device_id") == device_id or d.get("udid") == device_id or d.get("imei") == device_id:
                return d.get("display_name") or device_id
    except Exception:
        pass
    if device_id in ("mac-mini-cumulous", "mac-mini-local"):
        return "This Mac Mini"
    return device_id


def _expand_all_registered_ids(ids: list[str]) -> list[str]:
    """Ensure every known device identifier is a fan-out target (IMEI, UDID, device_id)."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(v: str) -> None:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    for i in ids or []:
        _add(str(i))

    try:
        from cumulous.devices import load_devices, probe_connected_device

        for d in load_devices().get("devices") or []:
            for key in ("device_id", "imei", "udid"):
                _add(str(d.get(key) or ""))
        probe = probe_connected_device() or {}
        for key in ("imei", "device_id", "udid"):
            _add(str(probe.get(key) or ""))
    except Exception:
        pass

    _add("mac-mini-cumulous")
    return out


def push_code_live(
    code: str,
    device_ids: list[str],
    *,
    purpose: str,
    challenge_id: str = "",
    expires_at: float = 0,
    requesting_user_id: str = "",
    requesting_device_id: str = "",
    replace_all_pending: bool = True,
) -> list[dict[str, Any]]:
    """Deliver exactly ONE live code payload to phones + Mac (no multi-window spam)."""
    digits = "".join(c for c in str(code) if c.isdigit())[:4].zfill(4)
    now = time.time()
    exp = float(expires_at) if expires_at else now + 30 * 60
    results: list[dict[str, Any]] = []

    ids = _expand_all_registered_ids(list(device_ids or []))

    location: dict[str, Any] = {}
    try:
        from cumulous.device_location import resolve_challenge_location

        location = resolve_challenge_location(
            requesting_device_id=requesting_device_id or (ids[0] if ids else ""),
            prefer_fresh_ip=True,
        )
    except Exception as e:
        location = {"ok": False, "error": str(e)[:120], "display_place": "Location unavailable"}

    data = prune_expired(now=now)
    # Hard-cap: only ONE active code total in pending store (Apple-style single sheet)
    if replace_all_pending:
        data["active"] = []
    else:
        data["active"] = [
            a
            for a in (data.get("active") or [])
            if a.get("purpose") != purpose or float(a.get("expires_at") or 0) <= now
        ]

    # Phone display URLs (LAN / Tailscale) for USB / Safari open
    phone_urls: list[str] = []
    try:
        from cumulous.install_invite import app_shell_urls, local_ip_candidates, tailscale_ip

        for h in local_ip_candidates():
            phone_urls.append(f"http://{h}:8765/challenge/display")
        ts = tailscale_ip()
        if ts:
            phone_urls.append(f"http://{ts}:8765/challenge/display")
        phone_urls.extend([u.rstrip("/") + "/#confirm" for u in app_shell_urls()[:3]])
    except Exception:
        phone_urls = ["http://127.0.0.1:8765/challenge/display"]

    payload = {
        "challenge_id": challenge_id,
        "code": digits,
        "purpose": purpose,
        "created_at": now,
        "expires_at": exp,
        "requesting_user_id": requesting_user_id,
        "requesting_device_id": requesting_device_id,
        "device_ids": ids,
        "device_labels": [_device_label(d) for d in ids],
        "apple_account_id": requesting_user_id,
        "broadcast_account": True,
        "title": "Confirm 4-Digit Code",
        "message": f"Cumulous verification code: {digits[0]} {digits[1]} {digits[2]} {digits[3]}",
        "phone_display_urls": phone_urls,
        "location": {
            "ok": bool(location.get("ok")),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "display_place": location.get("display_place") or "",
            "city": location.get("city") or "",
            "region": location.get("region") or "",
            "country": location.get("country") or "",
            "map_url": location.get("map_url") or "",
            "map_url_2x": location.get("map_url_2x") or "",
            "source": location.get("source") or "",
            "verified_paths": location.get("verified_paths") or 0,
        },
        "consumed": False,
    }
    data["active"] = [payload]  # exactly one
    save_pending(data)

    # USB-attached iPhone: queue shell push + try open display URL
    usb_result = _push_usb_iphone(digits, purpose=purpose, phone_urls=phone_urls, location=location)
    if usb_result:
        results.append(usb_result)

    log_path = ensure_internal() / "push_log.jsonl"
    mac_notified = False
    for did in ids:
        label = _device_label(did)
        channel = "pending_poll"
        status = "delivered_pending"
        is_mac = did in ("mac-mini-cumulous", "mac-mini-local") or (
            "mac" in did.lower() and "iphone" not in did.lower() and "ipad" not in did.lower()
        )
        if is_mac and not mac_notified:
            # One notification only — Streamlit owns the visual card (no extra dialogs)
            ok = _push_macos_notification_only(
                digits,
                purpose=purpose,
                place=str(location.get("display_place") or ""),
            )
            channel = "macos_notification"
            status = "delivered" if ok else "macos_failed"
            mac_notified = True
        # Mark USB device specially if matched
        if usb_result and did in (
            str(usb_result.get("device_id") or ""),
            str(usb_result.get("imei") or ""),
            str(usb_result.get("udid") or ""),
        ):
            channel = usb_result.get("channel") or channel
            status = usb_result.get("status") or status
        results.append(
            {
                "device_id": did,
                "display_name": label,
                "status": status,
                "channel": channel,
            }
        )
        with log_path.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": now,
                        "type": "challenge_code",
                        "device_id": did,
                        "display_name": label,
                        "purpose": purpose,
                        "challenge_id": challenge_id,
                        "status": status,
                        "channel": channel,
                        "location_ok": bool(location.get("ok")),
                        "single_active": True,
                    }
                )
                + "\n"
            )

    return results


def _push_macos_notification_only(
    digits: str,
    *,
    purpose: str,
    place: str = "",
) -> bool:
    """Single Notification Center banner — no secondary osascript dialog spam."""
    title = "Confirm 4-Digit Code"
    spaced = f"{digits[0]} {digits[1]} {digits[2]} {digits[3]}"
    place_line = (place or "See map in Cumulous").replace('"', "")
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "Code {spaced} · {place_line} · open Cumulous on iPhone" '
                f'with title "{title}" sound name "Glass"',
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


def _push_usb_iphone(
    digits: str,
    *,
    purpose: str,
    phone_urls: list[str],
    location: dict[str, Any],
) -> dict[str, Any] | None:
    """When USB iPhone is attached, deliver code via pending poll + shell open URL.

    True lock-screen APNs requires Apple push certs. Private Cumulous uses:
      1) pending_device_codes (polled by iOS app / web shell every 2s)
      2) queue_install_push-style live open of /challenge/display
      3) Mac notification already sent separately
    """
    try:
        from cumulous.devices import probe_connected_device
        from cumulous.install_invite import queue_install_push, best_app_url

        probe = probe_connected_device() or {}
        if not probe.get("udid") and not probe.get("imei"):
            return None
        did = str(probe.get("imei") or probe.get("device_id") or probe.get("udid") or "")
        udid = str(probe.get("udid") or "")
        name = str(probe.get("display_name") or "iPhone")
        display_url = (phone_urls or [best_app_url()])[0]
        # Reuse install-push channel so existing shell polls surface the challenge page
        try:
            queue_install_push(
                device_ids=[did, udid] if udid else [did],
                install_url=display_url,
                app_url=display_url,
                version="challenge",
                title="Confirm 4-Digit Code",
                body=(
                    f"Code {digits[0]} {digits[1]} {digits[2]} {digits[3]}. "
                    f"Near {location.get('display_place') or 'your location'}. "
                    f"Open Cumulous to enter on Mac."
                ),
                expires_sec=30 * 60,
            )
            channel = "usb_shell_push"
            status = "delivered_usb_shell"
        except Exception as e:
            channel = "usb_pending_only"
            status = f"shell_push_failed:{str(e)[:40]}"
        return {
            "device_id": did,
            "udid": udid,
            "imei": probe.get("imei"),
            "display_name": name,
            "status": status,
            "channel": channel,
            "display_url": display_url,
        }
    except Exception as e:
        return {
            "device_id": None,
            "status": "usb_error",
            "channel": "none",
            "error": str(e)[:120],
        }


def _matches_device(did: str, targets: list[str], apple_account: str, entry: dict) -> bool:
    if not did:
        return True  # open poll — show latest for LAN Cumulous clients
    if did in targets:
        return True
    for t in targets:
        ts, ds = str(t), str(did)
        if ts and ds and (ts in ds or ds in ts):
            return True
    # Account-wide broadcast
    if entry.get("broadcast_account") and apple_account:
        req = str(entry.get("requesting_user_id") or entry.get("apple_account_id") or "")
        if req and (req == apple_account or apple_account in req or req in apple_account):
            return True
    # Always allow if device is registered under same account as challenge
    try:
        from cumulous.devices import load_devices

        for d in load_devices().get("devices") or []:
            ids = {str(d.get("device_id") or ""), str(d.get("imei") or ""), str(d.get("udid") or "")}
            if did in ids:
                acct = str(d.get("apple_account_id") or d.get("owner_username") or "")
                req = str(entry.get("requesting_user_id") or "")
                if acct and req and (acct == req or acct in targets):
                    return True
                # CEO override devices always see codes
                if d.get("is_ceo_override"):
                    return True
    except Exception:
        pass
    return False


def active_codes_for_device(
    device_id: str = "",
    *,
    apple_account_id: str = "",
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Codes this device should display (live push surface)."""
    now = now if now is not None else time.time()
    data = prune_expired(now=now)
    out = []
    did = (device_id or "").strip()
    acct = (apple_account_id or "").strip()
    for a in data.get("active") or []:
        if a.get("consumed"):
            continue
        if float(a.get("expires_at") or 0) <= now:
            continue
        targets = list(a.get("device_ids") or [])
        if not _matches_device(did, targets, acct, a):
            continue
        loc = a.get("location") or {}
        out.append(
            {
                "challenge_id": a.get("challenge_id"),
                "code": a.get("code"),
                "purpose": a.get("purpose"),
                "expires_at": a.get("expires_at"),
                "message": a.get("message"),
                "device_labels": a.get("device_labels") or [],
                "seconds_left": max(0, int(float(a.get("expires_at") or 0) - now)),
                "location": loc,
                "map_url": loc.get("map_url") or "",
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "display_place": loc.get("display_place") or "",
            }
        )
    return out


def latest_active_code(
    *,
    device_id: str = "",
    apple_account_id: str = "",
    now: float | None = None,
) -> dict[str, Any] | None:
    codes = active_codes_for_device(
        device_id, apple_account_id=apple_account_id, now=now
    )
    if not codes:
        # Fallback: latest account-wide active (so iOS without device_id still works)
        now = now if now is not None else time.time()
        data = prune_expired(now=now)
        active = [
            a
            for a in (data.get("active") or [])
            if not a.get("consumed") and float(a.get("expires_at") or 0) > now
        ]
        if not active:
            return None
        active.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
        a = active[0]
        loc = a.get("location") or {}
        return {
            "challenge_id": a.get("challenge_id"),
            "code": a.get("code"),
            "purpose": a.get("purpose"),
            "expires_at": a.get("expires_at"),
            "message": a.get("message"),
            "device_labels": a.get("device_labels") or [],
            "device_ids": a.get("device_ids") or [],
            "seconds_left": max(0, int(float(a.get("expires_at") or 0) - now)),
            "location": loc,
            "map_url": loc.get("map_url") or "",
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "display_place": loc.get("display_place") or "",
        }
    codes.sort(key=lambda x: float(x.get("expires_at") or 0), reverse=True)
    return codes[0]


def mark_consumed(challenge_id: str = "", code: str = "") -> None:
    data = load_pending()
    digits = "".join(c for c in str(code) if c.isdigit())
    for a in data.get("active") or []:
        if challenge_id and a.get("challenge_id") == challenge_id:
            a["consumed"] = True
        elif digits and a.get("code") == digits:
            a["consumed"] = True
    save_pending(data)


def challenge_card_html(
    code: str,
    *,
    purpose: str = "verification",
    place: str = "",
    map_url: str = "",
    seconds_left: int = 0,
    show_digits: bool = True,
    title: str = "Confirm 4-Digit Code",
) -> str:
    """Apple-style 4-digit + map card. Map ≈ 1/3 of card height."""
    digits = "".join(c for c in str(code) if c.isdigit())[:4].zfill(4)
    boxes = (
        "".join(f'<span class="cs-pin-box">{d}</span>' for d in digits)
        if show_digits
        else '<div class="cs-pin-boxes-hidden">Code on your iPhone</div>'
    )
    if map_url:
        map_block = (
            f'<div class="cs-pin-map-wrap cs-pin-map-third">'
            f'<img class="cs-pin-map" src="{map_url}" alt="Request location map" '
            f'width="280" height="130" loading="eager" referrerpolicy="no-referrer"/>'
            f"</div>"
        )
    else:
        map_block = (
            '<div class="cs-pin-map-wrap cs-pin-map-third cs-pin-map-empty">'
            "Map loading…</div>"
        )
    place_html = place or "Approximate location"
    mins = max(0, seconds_left // 60) if seconds_left else 30
    safe_purpose = (purpose or "verification").replace("_", " ")
    return f"""
<div class="cs-pin-card" role="dialog" aria-label="Confirm 4-Digit Code">
  <div class="cs-pin-card-inner">
    <div class="cs-pin-title">{title}</div>
    <div class="cs-pin-sub">Cumulous · {safe_purpose}</div>
    <div class="cs-pin-boxes">{boxes}</div>
    <div class="cs-pin-place">{place_html}</div>
    {map_block}
    <div class="cs-pin-ttl">Valid about {mins} minutes · one code only</div>
  </div>
</div>
"""
