"""Clear completion state for UI actions (buttons show done / failed / running)."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from cumulous.paths import action_status_file, ensure_internal

Status = Literal["idle", "running", "ok", "error"]


def _load() -> dict[str, Any]:
    ensure_internal()
    p = action_status_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    ensure_internal()
    p = action_status_file()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def set_status(
    action_id: str,
    status: Status,
    *,
    message: str = "",
    detail: str = "",
) -> dict:
    data = _load()
    rec = {
        "action_id": action_id,
        "status": status,
        "message": message,
        "detail": detail,
        "updated_at": time.time(),
    }
    data[action_id] = rec
    _save(data)
    return rec


def get_status(action_id: str) -> dict:
    return _load().get(action_id) or {
        "action_id": action_id,
        "status": "idle",
        "message": "",
        "detail": "",
        "updated_at": 0,
    }


def clear_status(action_id: str) -> None:
    data = _load()
    data.pop(action_id, None)
    _save(data)


def badge_label(status: str) -> str:
    from cumulous.ux_copy import badge_ui

    label, _ = badge_ui(status)
    return label


def badge_color(status: str) -> str:
    from cumulous.ux_copy import badge_ui

    _, color = badge_ui(status)
    return color
