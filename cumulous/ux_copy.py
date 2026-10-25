"""CEO-facing UI copy — single source of truth.

Keeps Mac Streamlit, FastAPI progress, and iOS/web clients free of terminal
dumps, stack traces, and protocol error codes. Import this; do not duplicate.
"""

from __future__ import annotations

from typing import Any

# Phrases / tokens that must never appear in tab UI
_NOISE_MARKERS = (
    "traceback",
    "exception",
    "errorcode",
    "mberrordomain",
    "errno",
    'file "',
    "line ",
    "stdout",
    "stderr",
    "idevice",
    "returncode",
    "http/",
    "stack",
    "null pointer",
    ".py:",
    "assert ",
    "failed:",
    "mberror",
)


def is_technical_noise(text: str | None) -> bool:
    """True when *text* looks like a dump / protocol / stack fragment."""
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if any(m in low for m in _NOISE_MARKERS):
        return True
    # Long token with no spaces → id / hash / udid
    if len(t) > 40 and " " not in t:
        return True
    if "\n" in t and len(t) > 60:
        return True
    return False


def friendly_message(
    raw: str | None,
    *,
    fallback: str = "Something needs attention",
    allow_empty: bool = False,
) -> str:
    """Map any internal string to calm, short UI copy.

    Success titles must pass through unchanged when they are already plain English.
    Failure/noise mappings only apply to error-like or protocol-like text.
    """
    t = (raw or "").strip()
    if not t:
        return "" if allow_empty else fallback

    low = t.lower()

    # Already-good CEO copy — never rewrite
    _SUCCESS_PASS = {
        "completed",
        "verified",
        "paired",
        "pair ok",
        "tools ready",
        "phone tools ready",
        "settings saved",
        "account linked",
        "apple account linked",
        "iphone found",
        "apple device detected",
        "device registered",
        "backup authorized",
        "backup complete",
        "2fa ok",
        "code accepted",
        "unlocked",
        "restored",
        "media mirrored",
        "photo backup started",
        "install sent",
        "invites sent",
        "app install pushed",
        "notes written",
        "library updated",
        "tags updated",
        "removed from phone",
        "phone cleanup done",
    }
    if low in _SUCCESS_PASS or low.rstrip(".") in _SUCCESS_PASS:
        return t
    # Short positive phrases with no error markers
    if low.startswith(
        (
            "enter 2fa",
            "2fa next",
            "start secure",
            "backup authorized",
            "code sent",
            "running in the background",
            "still safe",
            "add-only",
            "saved securely",
        )
    ):
        return t

    # Domain mappings (error / wait states only)
    if "208" in t or "passcode" in low or "device locked" in low or "waiting for passcode" in low:
        return "Unlock the iPhone once when prompted"
    if "usb_required" in low or "plug the iphone" in low:
        return "Plug the iPhone into this Mac with USB"
    if "not_in_vault" in low or "not_backed_up" in low:
        return "Back this up in Cumulous first"
    if "awaiting_dual" in low:
        return "Waiting for both Mac and Nextcloud copies"
    # Only rewrite trust/pair when clearly a problem, not success
    if any(w in low for w in ("trust needed", "tap trust", "pair failed", "pairing failed", "not paired")):
        return "Unlock the phone and tap Trust"
    if "no device" in low or "no iphone" in low or "not connected" in low or "no_usb" in low:
        return "Connect the iPhone with a cable"
    if any(
        w in low
        for w in (
            "2fa rejected",
            "2fa failed",
            "totp rejected",
            "invalid totp",
            "bad 2fa",
            "security code wasn’t",
            "security code wasn't",
        )
    ):
        return "That security code wasn’t accepted"
    if "invalid" in low and "code" in low:
        return "That code wasn’t accepted — request a new one"
    if "expired" in low and "code" in low:
        return "That code expired — request a new one"
    if "unplug" in low or "usb unplugged" in low:
        return "Cable unplugged — continuing on Wi‑Fi when available"
    if "abort" in low or ("connection" in low and "error" in low) or low == "-4" or " error -4" in low:
        return "Connection paused — will continue automatically"
    # Digests / bare hashes alone
    hexish = low.replace("-", "")
    if len(t) >= 32 and hexish and all(c in "0123456789abcdef" for c in hexish):
        return "" if allow_empty else fallback

    if is_technical_noise(t):
        return fallback

    # Soften harsh prefixes without rewriting the whole sentence
    cleaned = (
        t.replace("ERROR:", "")
        .replace("Error:", "")
        .replace("Failed:", "")
        .replace("ERROR", "")
        .strip()
    )
    if len(cleaned) > 120:
        return fallback
    return cleaned or fallback


def client_error(raw: Any, *, status: str = "") -> str | None:
    """Public progress `error` field — None when healthy or wait-only."""
    if status in ("running", "complete", "idle", "cancelled"):
        return None
    if raw is None or str(raw).strip() == "":
        if status in ("needs_resume", "handoff", "awaiting_network"):
            return "Reconnecting — backup will continue"
        if status == "waiting_passcode":
            return None
        return None
    return friendly_message(str(raw), fallback="Paused — Cumulous will retry")


def progress_headline(percent_int: int, *, status: str = "") -> str:
    """Primary progress title — never “Complete” until finished."""
    pct = max(0, min(100, int(percent_int)))
    if status == "complete" or pct >= 100:
        return "Backup complete"
    return "Backup"


def progress_percent_label(percent_int: int) -> str:
    return f"{max(0, min(100, int(percent_int)))}%"


def badge_ui(status: str) -> tuple[str, str]:
    """Return (label, hex color) for action badges — soft palette."""
    s = (status or "idle").lower()
    if s == "running":
        return "Working", "#ffd60a"
    if s == "ok":
        return "Done", "#30d158"
    if s == "error":
        return "Needs a moment", "#ffd60a"  # amber, never terminal red
    return "", "#8e8e93"


def public_verification(session_ver: dict[str, Any] | None) -> dict[str, Any]:
    """Compact verification for clients — no paths or sample lists."""
    ver = session_ver or {}
    ok = int(ver.get("ok_samples") or 0)
    fail = int(ver.get("fail_samples") or 0)
    return {
        "ok": fail == 0,
        "checked": (ok + fail) > 0,
    }


def public_repair(session_repair: dict[str, Any] | None) -> dict[str, Any]:
    rep = session_repair or {}
    return {"ok": bool(rep.get("ok", True))}
