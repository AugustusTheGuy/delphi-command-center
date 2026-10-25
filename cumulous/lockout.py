"""Password attempt lockout: 10 fails → 1h; another 10 within 6h → 3h."""

from __future__ import annotations

import json
import time
from pathlib import Path

from cumulous.paths import ensure_internal, lockout_file

FAIL_THRESHOLD = 10
FIRST_LOCK_SEC = 3600  # 1 hour
SECOND_LOCK_SEC = 10800  # 3 hours
WINDOW_SEC = 6 * 3600  # 6 hours


def _load() -> dict:
    ensure_internal()
    lf = lockout_file()
    if not lf.exists():
        return {"fails": [], "locked_until": 0.0, "escalations": []}
    return json.loads(lf.read_text())


def _save(data: dict) -> None:
    ensure_internal()
    lf = lockout_file()
    lf.write_text(json.dumps(data, indent=2))
    try:
        lf.chmod(0o600)
    except OSError:
        pass


def is_locked(now: float | None = None) -> tuple[bool, float]:
    """Return (locked, seconds_remaining)."""
    now = now if now is not None else time.time()
    data = _load()
    until = float(data.get("locked_until") or 0)
    if until > now:
        return True, until - now
    return False, 0.0


def record_failure(now: float | None = None) -> dict:
    now = now if now is not None else time.time()
    data = _load()
    locked, rem = is_locked(now)
    if locked:
        return {"locked": True, "seconds_remaining": rem, "fail_count_window": 0}

    fails = [t for t in data.get("fails", []) if now - t < WINDOW_SEC]
    fails.append(now)
    data["fails"] = fails

    # Count fails since last lock ended
    escalations = data.get("escalations", [])
    recent_escalation = any(now - e < WINDOW_SEC for e in escalations)

    if len(fails) >= FAIL_THRESHOLD:
        # Clear fail window and apply lock
        data["fails"] = []
        if recent_escalation:
            data["locked_until"] = now + SECOND_LOCK_SEC
            lock_kind = "3h"
        else:
            data["locked_until"] = now + FIRST_LOCK_SEC
            lock_kind = "1h"
        escalations.append(now)
        data["escalations"] = [e for e in escalations if now - e < WINDOW_SEC * 2]
        _save(data)
        return {
            "locked": True,
            "lock_kind": lock_kind,
            "seconds_remaining": data["locked_until"] - now,
            "fail_count_window": 0,
        }

    _save(data)
    return {
        "locked": False,
        "fail_count_window": len(fails),
        "remaining_until_lock": FAIL_THRESHOLD - len(fails),
    }


def record_success(now: float | None = None) -> None:
    """Clear fail streak on success (does not clear active lock)."""
    now = now if now is not None else time.time()
    data = _load()
    locked, _ = is_locked(now)
    if not locked:
        data["fails"] = []
        _save(data)
