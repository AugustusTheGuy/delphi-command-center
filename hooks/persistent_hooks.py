"""Persistent hooks: TimeCopilot, EventManager, agent discovery on DHC lifecycle."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

HOOK_STATE = Path(__file__).resolve().parent.parent / "data" / "hook_state.json"


def _load() -> dict[str, Any]:
    HOOK_STATE.parent.mkdir(parents=True, exist_ok=True)
    if not HOOK_STATE.exists():
        return {"timecopilot": {}, "event_manager": {}, "runs": []}
    try:
        return json.loads(HOOK_STATE.read_text())
    except json.JSONDecodeError:
        return {"timecopilot": {}, "event_manager": {}, "runs": []}


def _save(data: dict[str, Any]) -> None:
    HOOK_STATE.write_text(json.dumps(data, indent=2))


def should_use_timecopilot(context: str) -> tuple[bool, str]:
    """Detect forecasting/anomaly/scheduling contexts."""
    keys = ("forecast", "predict", "anomaly", "time series", "trend", "schedule pattern", "cpu trend", "wifi pattern")
    lower = context.lower()
    if any(k in lower for k in keys):
        return True, "Time-series or predictive context detected — TimeCopilot hook eligible."
    return False, ""


def should_use_event_manager(context: str) -> tuple[bool, str]:
    keys = ("when ", "on event", "trigger", "if then", "automate when", "watch for", "alert when")
    lower = context.lower()
    if any(k in lower for k in keys):
        return True, "Event-driven language detected — EventManager hook eligible."
    return False, ""


def run_startup_hooks() -> dict[str, Any]:
    from core.agent_discovery import run_discovery_hook
    from core.openhuman_bridge import ensure_workspace, export_ceo_context, status as oh_status
    from core.video_library import build_catalog as build_video_catalog, run_maintenance_hook as video_maintain

    data = _load()
    oh = oh_status()
    if oh.get("installed"):
        ensure_workspace()
        export_ceo_context()
    try:
        from core.media_archive import nox_available
        if nox_available():
            video_maintain()
            video_catalog = build_video_catalog()
        else:
            video_catalog = {"entries": []}
    except OSError:
        video_catalog = {"entries": []}
    discovery = run_discovery_hook()
    tc_uses = [
        "System Status CPU/RAM trends",
        "WiFi anomaly baseline over time",
        "Agent task queue forecasting",
        "Nextcloud sync volume prediction",
        "Home energy usage patterns",
    ]
    em_uses = [
        "TV power on → Movie Mode scene",
        "Ollama offline → notify + fallback MLX",
        "Backup complete → log to OS Management",
        "PhantomCloak disconnect → alert Central Command",
        "New agent discovered → update Agents Dashboard",
    ]
    entry = {
        "at": datetime.now().isoformat(),
        "discovery_agents_ready": sum(1 for a in discovery["agents"] if a.get("installed")),
        "openhuman": oh,
        "video_catalog_count": len(video_catalog.get("entries", [])),
        "timecopilot_use_cases": tc_uses,
        "event_manager_use_cases": em_uses,
    }
    data["timecopilot"] = {"last_check": entry["at"], "use_cases": tc_uses}
    data["event_manager"] = {"last_check": entry["at"], "use_cases": em_uses}
    data["runs"] = [entry] + data.get("runs", [])[:50]
    _save(data)
    return {"discovery": discovery, "hooks": entry}


def evaluate_context_hooks(context: str) -> list[dict[str, str]]:
    """Called on every Central Command input and periodically while DHC open."""
    hooks: list[dict[str, str]] = []
    tc, tc_msg = should_use_timecopilot(context)
    if tc:
        hooks.append({"hook": "timecopilot", "action": "suggest_forecast_pipeline", "reason": tc_msg})
    em, em_msg = should_use_event_manager(context)
    if em:
        hooks.append({"hook": "event_manager", "action": "suggest_event_catalog_entry", "reason": em_msg})
    return hooks