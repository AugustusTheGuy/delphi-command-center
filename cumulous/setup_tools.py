"""Auto-install companion tooling where possible."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def ensure_libimobiledevice() -> dict[str, Any]:
    if which("idevicebackup2"):
        return {"ok": True, "idevicebackup2": which("idevicebackup2"), "action": "already_present"}
    brew = which("brew")
    if not brew:
        return {
            "ok": False,
            "action": "manual",
            "message": "Homebrew not found. Install from https://brew.sh then re-run setup.",
            "open_url": "https://brew.sh",
        }
    try:
        subprocess.run(
            [brew, "install", "libimobiledevice", "ideviceinstaller"],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as e:
        return {
            "ok": False,
            "action": "failed",
            "error": str(e),
            "message": "brew install libimobiledevice failed — run manually in Terminal.",
        }
    return {
        "ok": bool(which("idevicebackup2")),
        "idevicebackup2": which("idevicebackup2"),
        "action": "installed",
    }


def status_report() -> dict[str, Any]:
    return {
        "idevicebackup2": which("idevicebackup2"),
        "idevice_id": which("idevice_id"),
        "brew": which("brew"),
        "ollama": which("ollama"),
        "xcodebuild": which("xcodebuild"),
    }
