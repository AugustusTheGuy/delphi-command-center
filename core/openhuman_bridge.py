"""OpenHuman bridge — sidecar memory harness (local Ollama provider only)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

OPENHUMAN_APP = Path("/Applications/OpenHuman.app")
OPENHUMAN_WORKSPACE = Path("/Volumes/ExternalSSD/AI/openhuman-workspace")
MEMORY_EXPORT = Path.home() / "DelphiHomeController" / "data" / "openhuman_memory_export.json"
CEO_BRIEFING = Path.home() / "DelphiHomeController" / "data" / "CEO_BRIEFING.md"


def status() -> dict[str, Any]:
    installed = OPENHUMAN_APP.exists()
    workspace_ready = OPENHUMAN_WORKSPACE.exists()
    export_exists = MEMORY_EXPORT.exists()
    return {
        "installed": installed,
        "app_path": str(OPENHUMAN_APP),
        "workspace": str(OPENHUMAN_WORKSPACE),
        "workspace_ready": workspace_ready,
        "memory_export": str(MEMORY_EXPORT),
        "export_exists": export_exists,
        "provider_mode": "local_ollama_only",
        "checked_at": datetime.now().isoformat(),
    }


def ensure_workspace() -> tuple[bool, str]:
    if not Path("/Volumes/ExternalSSD").exists():
        return False, "ExternalSSD not mounted — OpenHuman workspace requires /Volumes/ExternalSSD"
    OPENHUMAN_WORKSPACE.mkdir(parents=True, exist_ok=True)
    return True, f"Workspace ready at {OPENHUMAN_WORKSPACE}"


def launch() -> tuple[bool, str]:
    if not OPENHUMAN_APP.exists():
        return False, "OpenHuman not installed — run: brew install --cask openhuman"
    ok, msg = ensure_workspace()
    if not ok:
        return False, msg
    try:
        subprocess.Popen(["open", "-a", "OpenHuman"], start_new_session=True)
        return True, "OpenHuman launched (configure local Ollama provider in app settings)."
    except OSError as e:
        return False, str(e)


def export_ceo_context() -> dict[str, Any]:
    """Read-only export of CEO briefing for OpenHuman Memory Tree seeding."""
    payload: dict[str, Any] = {
        "exported_at": datetime.now().isoformat(),
        "source": "DelphiHomeController",
        "type": "ceo_briefing_snapshot",
    }
    if CEO_BRIEFING.exists():
        text = CEO_BRIEFING.read_text(encoding="utf-8", errors="replace")
        payload["briefing_chars"] = len(text)
        payload["briefing_preview"] = text[:4000]
    MEMORY_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_EXPORT.write_text(json.dumps(payload, indent=2))
    return payload