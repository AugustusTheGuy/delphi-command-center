"""Backup wake policy: keep devices awake, log prior Auto-Lock, restore on any end.

Strategy (most automatic Apple allows without private APIs / MDM):
  1. Mac — caffeinate while session active; kill on end.
  2. iOS Cumulous app — UIApplication.isIdleTimerDisabled while power.keep_awake.
  3. System Auto-Lock — apps cannot write Settings. We:
       a) Push a local/remote prompt at backup start to open Display settings
          (or confirm in-app) and log the *previous* Auto-Lock choice the user
          reports / the app last stored.
       b) Push again on complete/cancel/abort with the exact previous value to restore.
  4. Snapshot is durable under ~/.cumulous/backup_power_state.json (mode 600).

Clients MUST call applyIdleTimer from /backup/progress.power and honor
pending_notifications + restore_auto_lock.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal

# Common iOS Auto-Lock options (seconds); 0 = Never
AUTO_LOCK_LABELS = {
    0: "Never",
    30: "30 Seconds",
    60: "1 Minute",
    120: "2 Minutes",
    180: "3 Minutes",
    240: "4 Minutes",
    300: "5 Minutes",
}


def _path() -> Path:
    return ensure_internal() / "backup_power_state.json"


def _load() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {"active": False, "history": []}
    try:
        data = json.loads(p.read_text())
        if "history" not in data:
            data["history"] = []
        return data
    except Exception:
        return {"active": False, "history": []}


def _save(data: dict[str, Any]) -> None:
    ensure_internal()
    p = _path()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def _label(seconds: int | None) -> str:
    if seconds is None:
        return "Unknown (set in Settings → Display)"
    return AUTO_LOCK_LABELS.get(int(seconds), f"{int(seconds)} Seconds")


def _mac_notify(title: str, body: str) -> bool:
    try:
        safe_t = title.replace('"', "'")[:80]
        safe_b = body.replace('"', "'")[:180]
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{safe_b}" with title "{safe_t}" sound name "Glass"',
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


def _queue_push(data: dict[str, Any], *, kind: str, title: str, body: str, actions: list[dict] | None = None) -> dict[str, Any]:
    note = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "title": title,
        "body": body,
        "actions": actions or [],
        "created_at": time.time(),
        "delivered": False,
    }
    pending = list(data.get("pending_notifications") or [])
    pending.append(note)
    # Keep last 8
    data["pending_notifications"] = pending[-8:]
    return note


def begin_backup_wake_policy(
    *,
    session_id: str = "",
    device_name: str = "",
    previous_auto_lock_seconds: int | None = None,
) -> dict[str, Any]:
    """Start keep-awake window; snapshot prior Auto-Lock if known; push prompt.

    Idempotent while already active for the same session — does not spam
    notifications or flip restore state.
    """
    data = _load()
    already_active = bool(data.get("active"))
    same_session = already_active and (
        not session_id or data.get("session_id") == session_id
    )

    # Preserve existing snapshot if already mid-backup
    if already_active and data.get("pre_backup_snapshot"):
        snap = data["pre_backup_snapshot"]
    else:
        # Prefer newly reported value; else last known from device client
        prior = previous_auto_lock_seconds
        if prior is None:
            prior = data.get("last_known_auto_lock_seconds")
        snap = {
            "auto_lock_seconds": prior,
            "auto_lock_label": _label(prior if prior is not None else None),
            "ios_idle_timer_disabled_before": False,
            "captured_at": time.time(),
        }

    if previous_auto_lock_seconds is not None:
        snap["auto_lock_seconds"] = int(previous_auto_lock_seconds)
        snap["auto_lock_label"] = _label(int(previous_auto_lock_seconds))
        data["last_known_auto_lock_seconds"] = int(previous_auto_lock_seconds)

    prior_label = snap.get("auto_lock_label") or "your previous setting"

    # Drop stale restore pushes if we are (re)engaging mid-backup
    pending = [
        n
        for n in (data.get("pending_notifications") or [])
        if n.get("kind") != "auto_lock_restore"
    ]
    data["pending_notifications"] = pending

    note_start = None
    if not same_session:
        note_start = _queue_push(
            data,
            kind="auto_lock_start",
            title="Cumulous · Keep screen awake",
            body=(
                f"Backup of {device_name or 'iPhone'} — keep Cumulous open. "
                f"App reasserts no-dim every 0.25s (idle timer off + silent keep-alive). "
                f"Optional system Auto-Lock → Never (was: {prior_label}). "
                f"We’ll remind you to restore {prior_label} when backup ends."
            ),
            actions=[
                {"id": "open_display_settings", "title": "Open Display Settings"},
                {"id": "ack_keep_awake", "title": "Keep Awake"},
            ],
        )
        _mac_notify(
            "Cumulous · Keep screen awake",
            f"{device_name or 'Device'} backup — screen wake on. Restore Auto-Lock ({prior_label}) when done.",
        )

    data.update(
        {
            "active": True,
            "session_id": session_id or data.get("session_id") or "",
            "device_name": device_name or data.get("device_name") or "",
            "started_at": data.get("started_at") or time.time(),
            "pre_backup_snapshot": snap,
            "end_reason": None,
            "ios": {
                "disable_idle_timer": True,
                "reassert_interval_sec": 0.25,
                "silent_audio_keepalive": True,
                "prompt_auto_lock_never": True,
                "settings_url_candidates": [
                    # Best-effort deep links (iOS may ignore some)
                    "App-prefs:root=DISPLAY&path=AUTOLOCK",
                    "prefs:root=DISPLAY&path=AUTOLOCK",
                    "App-prefs:root=DISPLAY",
                ],
                "restore_on_end": True,
            },
            "mac": {"caffeinate": True},
        }
    )
    if note_start:
        data["latest_start_notification_id"] = note_start["id"]
    _save(data)
    return data


def record_client_auto_lock_snapshot(
    *,
    auto_lock_seconds: int | None = None,
    idle_timer_disabled_before: bool | None = None,
    device_id: str = "",
) -> dict[str, Any]:
    """iOS app reports previous Auto-Lock (or last known) before/when engaging wake."""
    data = _load()
    snap = dict(data.get("pre_backup_snapshot") or {})
    if auto_lock_seconds is not None:
        snap["auto_lock_seconds"] = int(auto_lock_seconds)
        snap["auto_lock_label"] = _label(int(auto_lock_seconds))
        data["last_known_auto_lock_seconds"] = int(auto_lock_seconds)
    if idle_timer_disabled_before is not None:
        snap["ios_idle_timer_disabled_before"] = bool(idle_timer_disabled_before)
    snap["device_id"] = device_id
    snap["updated_at"] = time.time()
    if data.get("active"):
        data["pre_backup_snapshot"] = snap
    else:
        # Store for next backup if reported early
        data["pre_backup_snapshot"] = snap
    _save(data)
    return {"ok": True, "snapshot": snap}


def end_backup_wake_policy(*, reason: str = "complete") -> dict[str, Any]:
    """Restore wake policy for any end: complete | cancelled | error_terminal."""
    data = _load()
    snap = data.get("pre_backup_snapshot") or {}
    prior_sec = snap.get("auto_lock_seconds")
    if prior_sec is None:
        prior_sec = data.get("last_known_auto_lock_seconds")
    prior_label = _label(int(prior_sec) if prior_sec is not None else None)

    note = _queue_push(
        data,
        kind="auto_lock_restore",
        title="Cumulous · Restore Auto-Lock",
        body=(
            f"Backup {reason}. Return Auto-Lock to {prior_label} "
            f"(Settings → Display & Brightness → Auto-Lock). "
            f"Cumulous has restored normal app sleep behavior."
        ),
        actions=[
            {"id": "open_display_settings", "title": "Open Display Settings"},
            {"id": "ack_restored", "title": "Done"},
        ],
    )
    _mac_notify(
        "Cumulous · Restore Auto-Lock",
        f"Backup {reason}. Restore Auto-Lock to {prior_label} if you changed it.",
    )

    # History for audit
    hist = list(data.get("history") or [])
    hist.append(
        {
            "ended_at": time.time(),
            "reason": reason,
            "restored_auto_lock_seconds": prior_sec,
            "restored_auto_lock_label": prior_label,
            "session_id": data.get("session_id"),
        }
    )

    out = {
        "active": False,
        "ended_at": time.time(),
        "end_reason": reason,
        "pre_backup_snapshot": snap,
        "restored_auto_lock_seconds": prior_sec,
        "restored_auto_lock_label": prior_label,
        "pending_notifications": data.get("pending_notifications") or [],
        "latest_restore_notification_id": note["id"],
        "ios": {
            "disable_idle_timer": False,
            "restore_system_auto_lock": True,
            "restore_to_seconds": prior_sec,
            "restore_to_label": prior_label,
            "settings_url_candidates": [
                "App-prefs:root=DISPLAY&path=AUTOLOCK",
                "prefs:root=DISPLAY&path=AUTOLOCK",
                "App-prefs:root=DISPLAY",
            ],
        },
        "mac": {"caffeinate": False},
        "history": hist[-40:],
        "last_known_auto_lock_seconds": prior_sec
        if prior_sec is not None
        else data.get("last_known_auto_lock_seconds"),
    }
    _save(out)

    # Stop Mac sleep prevention (session caffeinate children exit with backup;
    # only kill if no idevicebackup2 remains)
    try:
        alive = subprocess.run(
            ["pgrep", "-x", "idevicebackup2"],
            capture_output=True,
            timeout=3,
            check=False,
        )
        if alive.returncode != 0:
            subprocess.run(["pkill", "-x", "caffeinate"], check=False, capture_output=True, timeout=3)
    except Exception:
        pass
    return out


def ack_notification(notification_id: str) -> dict[str, Any]:
    data = _load()
    pending = []
    for n in data.get("pending_notifications") or []:
        if n.get("id") == notification_id:
            n = {**n, "delivered": True, "acked_at": time.time()}
        pending.append(n)
    data["pending_notifications"] = pending
    _save(data)
    return {"ok": True}


def power_policy_for_clients() -> dict[str, Any]:
    """Compact client contract polled with /backup/progress."""
    st = _load()
    pending = [n for n in (st.get("pending_notifications") or []) if not n.get("delivered")]
    snap = st.get("pre_backup_snapshot") or {}
    if st.get("active"):
        # While keep_awake, never surface restore pushes (false-complete noise)
        pending = [n for n in pending if n.get("kind") != "auto_lock_restore"]
        return {
            "keep_awake": True,
            "ios_disable_idle_timer": True,
            "ios_reassert_interval_sec": 0.25,
            "ios_silent_audio_keepalive": True,
            "mac_caffeinate": True,
            "session_id": st.get("session_id"),
            "prompt_auto_lock_never": True,
            "previous_auto_lock_seconds": snap.get("auto_lock_seconds"),
            "previous_auto_lock_label": snap.get("auto_lock_label"),
            "settings_url_candidates": (st.get("ios") or {}).get("settings_url_candidates") or [],
            "pending_notifications": pending,
            "ios_hint": (
                f"No dim while Cumulous is open (idle timer off, reassert every 0.25s). "
                f"Logged prior Auto-Lock: {snap.get('auto_lock_label') or 'unknown'}. "
                f"We’ll prompt to restore it when backup ends."
            ),
        }
    return {
        "keep_awake": False,
        "ios_disable_idle_timer": False,
        "ios_reassert_interval_sec": 0.25,
        "mac_caffeinate": False,
        "restore_system_auto_lock": True,
        "restore_to_seconds": st.get("restored_auto_lock_seconds"),
        "restore_to_label": st.get("restored_auto_lock_label"),
        "settings_url_candidates": (st.get("ios") or {}).get("settings_url_candidates") or [],
        "pending_notifications": pending,
        "end_reason": st.get("end_reason"),
        "ios_hint": (
            f"Backup ended ({st.get('end_reason') or 'done'}). "
            f"Restore Auto-Lock to {st.get('restored_auto_lock_label') or 'previous setting'} "
            f"if you changed it."
        ),
    }


# Back-compat aliases used by backup_session
load_power_state = _load
save_power_state = _save
