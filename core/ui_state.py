"""Remember the last page so the next open returns there."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_FILE = DATA_DIR / "ui_state.json"
ALLOWED = {
    "home",
    "settings",
    "user_profile",
    "orchestrator",
    "central_command",
    "agent_monitor",
    "agents_dashboard",
    "system_status",
    "project_management",
    "home_management",
    "nextcloud",
    "video_library",
    "tv_remote",
    "os_management",
    "github_hf",
    "phantomcloak",
}


def load_page() -> str:
    if not STATE_FILE.exists():
        return "home"
    try:
        raw = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return "home"
    page = raw.get("page") if isinstance(raw, dict) else None
    if page in ALLOWED:
        return str(page)
    return "home"


def save_page(page: str) -> str:
    if page not in ALLOWED:
        page = "home"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"page": page}, indent=2))
    return page
