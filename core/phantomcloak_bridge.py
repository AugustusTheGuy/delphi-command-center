"""PhantomCloak bridge — version check + launch from DHC."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

PHANTOM_ROOT = Path.home() / "Desktop" / "PhantomCloak"
SESSION_FILE = Path.home() / ".phantomcloak" / "last_session.json"
VERSION_FILE = PHANTOM_ROOT / "VERSION"
CLIENT_MAIN = PHANTOM_ROOT / "client" / "phantomcloak.py"


def status() -> dict[str, Any]:
    installed = CLIENT_MAIN.exists()
    version = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "unknown"
    session = None
    if SESSION_FILE.exists():
        try:
            session = json.loads(SESSION_FILE.read_text())
        except json.JSONDecodeError:
            session = {"raw": "corrupt"}
    return {
        "installed": installed,
        "path": str(PHANTOM_ROOT),
        "version": version,
        "client": str(CLIENT_MAIN),
        "last_session": session,
        "checked_at": datetime.now().isoformat(),
    }


def launch() -> tuple[bool, str]:
    if not CLIENT_MAIN.exists():
        return False, "PhantomCloak not found at ~/Desktop/PhantomCloak"
    cmd = ["python3", str(CLIENT_MAIN)]
    try:
        subprocess.Popen(
            cmd,
            cwd=str(PHANTOM_ROOT),
            env={"PYTHONPATH": str(PHANTOM_ROOT)},
            start_new_session=True,
        )
        return True, "PhantomCloak launched (restores last session)."
    except OSError as e:
        return False, str(e)


def verify_up_to_date() -> dict[str, Any]:
    """Best-effort: compare VERSION mtime; full git pull optional in install script."""
    st = status()
    st["up_to_date"] = st["installed"]
    if PHANTOM_ROOT.is_dir() and (PHANTOM_ROOT / ".git").exists():
        try:
            out = subprocess.check_output(
                ["git", "-C", str(PHANTOM_ROOT), "status", "-uno", "--porcelain"],
                text=True,
                timeout=10,
            )
            st["up_to_date"] = out.strip() == ""
            st["git_dirty"] = out.strip() != ""
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return st