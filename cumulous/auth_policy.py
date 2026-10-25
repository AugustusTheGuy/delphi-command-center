"""Auth policy for Cumulous CP builds.

CEO: 2FA / 4-digit challenge gates stay OFF until explicitly re-enabled.
Do not re-enable 2FA unless CEO says so. Keep code paths for later.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal


def _policy_path() -> Path:
    return ensure_internal() / "auth_policy.json"


def load_auth_policy() -> dict[str, Any]:
    p = _policy_path()
    env_skip = os.environ.get("CUMULOUS_SKIP_2FA", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    # Default: skip 2FA until CEO explicitly re-enables (CUMULOUS_SKIP_2FA=0)
    default_skip = True
    data: dict[str, Any] = {
        "skip_2fa": default_skip,
        "skip_challenge_codes": default_skip,
        "note": "Verification paused — do not re-enable 2FA until CEO asks",
    }
    if p.exists():
        try:
            import json

            disk = json.loads(p.read_text())
            if isinstance(disk, dict):
                data.update(disk)
        except Exception:
            pass
    if env_skip or os.environ.get("CUMULOUS_SKIP_2FA", "") == "":
        # env unset → keep default_skip; env=1 forces skip; env=0 forces require
        if os.environ.get("CUMULOUS_SKIP_2FA", "").strip().lower() in (
            "0",
            "false",
            "no",
            "off",
        ):
            data["skip_2fa"] = False
            data["skip_challenge_codes"] = False
        elif env_skip:
            data["skip_2fa"] = True
            data["skip_challenge_codes"] = True
    return data


def save_auth_policy(data: dict[str, Any]) -> None:
    import json

    ensure_internal()
    _policy_path().write_text(json.dumps(data, indent=2))


def auth_required_for_backup() -> bool:
    """False = backups/connect proceed without 4-digit or TOTP."""
    pol = load_auth_policy()
    return not bool(pol.get("skip_2fa", True)) and not bool(
        pol.get("skip_challenge_codes", True)
    )


def verification_paused_message() -> str:
    pol = load_auth_policy()
    return str(pol.get("note") or "Verification paused for this build")
