"""User profiles with colors, avatar, and per-tab visibility."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROFILES_DIR = DATA_DIR / "profiles"

ALL_TABS = [
    "user_profile",
    "orchestrator",
    "central_command",
    "agent_monitor",
    "agents_dashboard",
    "system_status",
    "project_management",
    "home_management",
    "nextcloud",
    "tv_remote",
    "os_management",
    "github_hf",
    "phantomcloak",
    "video_library",
]

DEFAULT_TAB_STATE = {tab: True for tab in ALL_TABS}


def _profile_path(profile_id: str) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILES_DIR / f"{profile_id}.json"


def list_profiles() -> List[Dict[str, Any]]:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            p = json.loads(path.read_text())
            profiles.append({
                "id": p.get("id", path.stem),
                "name": p.get("name", "Unnamed"),
                "primary_color": p.get("primary_color", "#C5CCD6"),
                "avatar": p.get("avatar"),
            })
        except Exception:
            continue
    return profiles


def load_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    path = _profile_path(profile_id)
    if not path.exists():
        return None
    profile = json.loads(path.read_text())
    if "password" in profile:
        profile.pop("password", None)
        save_profile(profile)
    return profile


def save_profile(profile: Dict[str, Any]) -> str:
    pid = profile.get("id") or str(uuid.uuid4())
    profile["id"] = pid
    profile.pop("password", None)
    profile["updated_at"] = datetime.now().isoformat()
    _profile_path(pid).write_text(json.dumps(profile, indent=2))
    return pid


def create_profile(
    name: str,
    primary: str = "#C5CCD6",
    secondary: str = "#22C55E",
    tertiary: str = "#070809",
    enabled_tabs: Optional[Dict[str, bool]] = None,
) -> str:
    profile = {
        "id": str(uuid.uuid4()),
        "name": name,
        "primary_color": primary,
        "secondary_color": secondary,
        "tertiary_color": tertiary,
        "font_color": primary,
        "avatar": None,
        "enabled_tabs": enabled_tabs or dict(DEFAULT_TAB_STATE),
        "created_at": datetime.now().isoformat(),
    }
    return save_profile(profile)