"""Jellyfin and Sonarr addresses saved on this Mac. Environment values win. Keys stay in the file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlencode

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SERVICES_FILE = DATA_DIR / "media_services.json"

_FIELDS = (
    ("JELLYFIN_URL", "jellyfin_url"),
    ("JELLYFIN_API_KEY", "jellyfin_api_key"),
    ("SONARR_URL", "sonarr_url"),
    ("SONARR_API_KEY", "sonarr_api_key"),
)


def _read() -> dict:
    if not SERVICES_FILE.exists():
        return {}
    try:
        raw = json.loads(SERVICES_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_media_services() -> dict:
    raw = _read()
    loaded = {}
    for env_name, key in _FIELDS:
        from_env = os.environ.get(env_name, "").strip()
        if from_env:
            loaded[key] = from_env
        else:
            loaded[key] = str(raw.get(key) or "").strip()
    return loaded


def save_media_services(jellyfin_url: str, jellyfin_api_key: str, sonarr_url: str, sonarr_api_key: str) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "jellyfin_url": jellyfin_url.strip(),
        "jellyfin_api_key": jellyfin_api_key.strip(),
        "sonarr_url": sonarr_url.strip(),
        "sonarr_api_key": sonarr_api_key.strip(),
    }
    SERVICES_FILE.write_text(json.dumps(payload, indent=2))
    os.chmod(SERVICES_FILE, 0o600)
    return load_media_services()


def connected(url: str, key: str) -> bool:
    return bool(url.strip() and key.strip())


def connection_summary() -> str:
    services = load_media_services()
    jellyfin = "connected" if connected(services["jellyfin_url"], services["jellyfin_api_key"]) else "not connected"
    sonarr = "connected" if connected(services["sonarr_url"], services["sonarr_api_key"]) else "not connected"
    return f"Jellyfin is {jellyfin}. Sonarr is {sonarr}."


def jellyfin_items_url(base: str) -> str:
    query = urlencode({
        "Recursive": "true",
        "IncludeItemTypes": "Movie,Series,Episode",
        "Limit": "400",
    })
    return f"{base.rstrip('/')}/Items?{query}"


def sonarr_series_url(base: str) -> str:
    return f"{base.rstrip('/')}/api/v3/series"
