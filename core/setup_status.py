"""Plain setup checklist for the front page. It never includes a key or a password."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def setup_status() -> list[dict]:
    from core.media_archive import nox_available
    from core.media_services import connected, load_media_services

    services = load_media_services()
    jellyfin_ok = connected(services["jellyfin_url"], services["jellyfin_api_key"])
    sonarr_ok = connected(services["sonarr_url"], services["sonarr_api_key"])
    return [
        {
            "label": "Drive",
            "ok": nox_available(),
            "detail": "ExternalSSD is mounted." if nox_available() else "ExternalSSD is not mounted.",
        },
        {
            "label": "Jellyfin",
            "ok": jellyfin_ok,
            "detail": "Connected." if jellyfin_ok else "Not connected.",
        },
        {
            "label": "Sonarr",
            "ok": sonarr_ok,
            "detail": "Connected." if sonarr_ok else "Not connected.",
        },
    ]
