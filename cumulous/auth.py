"""BEARACCOUNT + users; bcrypt hashes; first-run flow."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import bcrypt

from cumulous.lockout import is_locked, record_failure, record_success
from cumulous.password_policy import validate_password
from cumulous.paths import ensure_internal, secrets_file
from cumulous.totp_2fa import enroll as enroll_totp
from cumulous.totp_2fa import load_secret, verify_totp

BEARACCOUNT_ROLE = "bearaccount"
USER_ROLE = "user"


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def load_secrets() -> dict[str, Any]:
    ensure_internal()
    sf = secrets_file()
    if not sf.exists():
        return {
            "bearaccount_verified": False,
            "users": [],
            "ceo_override_device_ids": [],
            "site_policy": {
                "first_backup_location_label": "",
                "allowed_wifi_ssids": [],
            },
            "settings": default_backup_settings(),
        }
    data = json.loads(sf.read_text())
    return data


def save_secrets(data: dict[str, Any]) -> None:
    ensure_internal()
    sf = secrets_file()
    sf.write_text(json.dumps(data, indent=2))
    os.chmod(sf, 0o600)


def default_backup_settings() -> dict:
    return {
        "schedule_hours": 12,
        "schedule_mode": "persistent",  # standard | persistent
        "midnight_mode": "persistent",
        "change_driven_mode": "persistent",
        "persistent_backups": True,
        "categories": [
            "photos",
            "videos",
            "files",
            "contacts",
            "sms",
            "notes",
            "app_data",
            "keychain_via_system_backup",
        ],
    }


def bearaccount_exists() -> bool:
    data = load_secrets()
    if not data.get("bearaccount_verified"):
        return False
    return any(u.get("role") == BEARACCOUNT_ROLE for u in data.get("users", []))


def create_bearaccount(username: str, password: str) -> dict:
    ok, msg = validate_password(password)
    if not ok:
        raise ValueError(msg)
    data = load_secrets()
    if bearaccount_exists():
        raise ValueError("BEARACCOUNT already verified; use CEO Override to edit.")
    # remove incomplete bear users
    data["users"] = [u for u in data.get("users", []) if u.get("role") != BEARACCOUNT_ROLE]
    data["users"].append(
        {
            "username": username,
            "password_hash": _hash(password),
            "role": BEARACCOUNT_ROLE,
            "device_ids": [],
            "created_at": time.time(),
        }
    )
    totp_info = enroll_totp(account_name=username)
    data["bearaccount_verified"] = True
    data["bearaccount_username"] = username
    save_secrets(data)
    return {
        "username": username,
        "totp_secret": totp_info["secret"],
        "otpauth_uri": totp_info["otpauth_uri"],
        "message": "BEARACCOUNT created. Scan the 2FA code with your authenticator app (shown once).",
    }


def create_user(
    username: str,
    password: str,
    *,
    apple_id_hint: str = "",
    device_ids: list[str] | None = None,
) -> dict:
    ok, msg = validate_password(password)
    if not ok:
        raise ValueError(msg)
    if not bearaccount_exists():
        raise ValueError("Create BEARACCOUNT first.")
    data = load_secrets()
    for u in data["users"]:
        if u["username"] == username:
            raise ValueError("Username already exists.")
    data["users"].append(
        {
            "username": username,
            "password_hash": _hash(password),
            "role": USER_ROLE,
            "apple_id_hint": apple_id_hint,  # never a secret email in git; runtime only
            "device_ids": list(device_ids or []),
            "created_at": time.time(),
        }
    )
    save_secrets(data)
    return {"username": username, "role": USER_ROLE}


def authenticate(username: str, password: str, *, totp_code: str | None = None) -> dict:
    locked, rem = is_locked()
    if locked:
        return {"ok": False, "error": "locked", "seconds_remaining": rem}

    data = load_secrets()
    user = next((u for u in data.get("users", []) if u["username"] == username), None)
    if not user or not _check(password, user.get("password_hash", "")):
        info = record_failure()
        return {"ok": False, "error": "invalid_credentials", **info}

    secret = load_secret()
    if secret and totp_code is not None:
        if not verify_totp(secret, totp_code):
            info = record_failure()
            return {"ok": False, "error": "invalid_totp", **info}

    record_success()
    return {
        "ok": True,
        "username": username,
        "role": user.get("role"),
        "device_ids": user.get("device_ids", []),
    }


def change_password(username: str, new_password: str) -> bool:
    ok, msg = validate_password(new_password)
    if not ok:
        raise ValueError(msg)
    data = load_secrets()
    for u in data.get("users", []):
        if u["username"] == username:
            u["password_hash"] = _hash(new_password)
            save_secrets(data)
            return True
    return False


def register_ceo_override_devices(device_ids: list[str]) -> None:
    data = load_secrets()
    existing = set(data.get("ceo_override_device_ids") or [])
    existing.update(d for d in device_ids if d)
    data["ceo_override_device_ids"] = sorted(existing)
    save_secrets(data)


def register_user_devices(username: str, device_ids: list[str]) -> None:
    data = load_secrets()
    for u in data.get("users", []):
        if u["username"] == username:
            cur = set(u.get("device_ids") or [])
            cur.update(d for d in device_ids if d)
            u["device_ids"] = sorted(cur)
            save_secrets(data)
            return
    raise ValueError("user not found")
