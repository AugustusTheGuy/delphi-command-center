"""Path resolution for Cumulous secrets (internal) and vault (ExternalSSD).

Paths re-read CUMULOUS_HOME each call so tests can isolate without clobbering ~/.cumulous.
"""

from __future__ import annotations

import os
from pathlib import Path

EXTERNALSSD_ROOT = Path("/Volumes/ExternalSSD")
VAULT_DIRNAME = "CumulousVault"


def internal_root() -> Path:
    return Path(os.environ.get("CUMULOUS_HOME", Path.home() / ".cumulous")).expanduser()


def secrets_file() -> Path:
    return internal_root() / "secrets.json"


def totp_file() -> Path:
    return internal_root() / "totp.secret"


def salt_file() -> Path:
    return internal_root() / "salt.bin"


def sessions_file() -> Path:
    return internal_root() / "sessions.json"


def devices_file() -> Path:
    return internal_root() / "devices.json"


def lockout_file() -> Path:
    return internal_root() / "lockout.json"


def ceo_override_md() -> Path:
    return internal_root() / "CEOOVERRIDE.md"


def challenges_file() -> Path:
    return internal_root() / "challenges.json"


def apple_accounts_file() -> Path:
    return internal_root() / "apple_accounts.json"


def secrets_2x_file() -> Path:
    """CEO-only 2FA secrets per Apple Account (never git)."""
    return internal_root() / "2xsecrets"


def action_status_file() -> Path:
    return internal_root() / "action_status.json"


def restore_export_root() -> Path:
    """Mac Mini folder where decrypted restore trees are written for viewing."""
    if externalssd_mounted() and not os.environ.get("CUMULOUS_FORCE_INTERNAL_VAULT"):
        d = EXTERNALSSD_ROOT / "CumulousRestore"
    else:
        d = Path.home() / "CumulousRestore"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_incoming_root() -> Path:
    if externalssd_mounted() and not os.environ.get("CUMULOUS_FORCE_INTERNAL_VAULT"):
        d = EXTERNALSSD_ROOT / "CumulousIncoming"
    else:
        d = Path.home() / "CumulousIncoming"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Back-compat aliases (call sites may still import names — rebind via properties below)
# Prefer functions; keep module-level names as callables for minimal breakage where imported as symbols used as paths incorrectly.

def ensure_internal() -> Path:
    root = internal_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def externalssd_mounted() -> bool:
    return EXTERNALSSD_ROOT.is_dir()


def vault_root(prefer_nox: bool = True) -> Path:
    """Bulk vault: ExternalSSD when mounted, else internal fallback for offline tests."""
    if prefer_nox and externalssd_mounted() and not os.environ.get("CUMULOUS_FORCE_INTERNAL_VAULT"):
        root = EXTERNALSSD_ROOT / VAULT_DIRNAME
    else:
        root = internal_root() / "vault_fallback"
    root.mkdir(parents=True, exist_ok=True)
    return root


def secrets_replica_dir() -> Path | None:
    if not externalssd_mounted() or os.environ.get("CUMULOUS_FORCE_INTERNAL_VAULT"):
        return None
    d = EXTERNALSSD_ROOT / VAULT_DIRNAME / ".secrets_replica"
    d.mkdir(parents=True, exist_ok=True)
    return d


def device_dir(device_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_ ." else "_" for c in device_id).strip() or "unknown"
    d = vault_root() / "devices" / safe
    d.mkdir(parents=True, exist_ok=True)
    (d / "generations").mkdir(exist_ok=True)
    (d / "blobs").mkdir(exist_ok=True)
    (d / "verify").mkdir(exist_ok=True)
    return d


