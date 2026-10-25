"""Shared account TOTP (one seed for all device vault unlocks)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import pyotp

from cumulous.paths import ensure_internal, totp_file


def generate_secret() -> str:
    return pyotp.random_base32()


def save_secret(secret: str, path: Path | None = None) -> Path:
    ensure_internal()
    path = path or totp_file()
    path.write_text(secret.strip())
    os.chmod(path, 0o600)
    return path


def load_secret(path: Path | None = None) -> str | None:
    path = path or totp_file()
    if not path.exists():
        return None
    return path.read_text().strip() or None


def enroll(issuer: str = "Cumulous", account_name: str = "DelphiBEAR") -> dict:
    """Create and persist shared TOTP; return secret + otpauth URI for QR."""
    secret = generate_secret()
    save_secret(secret)
    uri = provisioning_uri(secret, issuer=issuer, account_name=account_name)
    return {"secret": secret, "otpauth_uri": uri, "issuer": issuer, "account": account_name}


def provisioning_uri(secret: str, *, issuer: str = "Cumulous", account_name: str = "DelphiBEAR") -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=account_name, issuer_name=issuer)


def current_code(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def verify_totp(secret: str, code: str, *, window: int = 1) -> bool:
    if not secret or not code:
        return False
    digits = "".join(c for c in str(code).strip() if c.isdigit())
    if len(digits) != 6:
        return False
    return bool(pyotp.TOTP(secret).verify(digits, valid_window=window))
