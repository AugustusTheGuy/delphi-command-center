"""AES-GCM vault encryption with password-derived keys (PBKDF2)."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from cumulous.paths import ensure_internal, salt_file

PBKDF2_ITERATIONS = 480_000
KEY_LEN = 32
NONCE_LEN = 12


def _get_or_create_salt() -> bytes:
    ensure_internal()
    sf = salt_file()
    if sf.exists():
        return sf.read_bytes()
    salt = secrets.token_bytes(32)
    sf.write_bytes(salt)
    os.chmod(sf, 0o600)
    return salt


def derive_key(password: str, salt: bytes | None = None, *, device_id: str = "") -> bytes:
    salt = salt or _get_or_create_salt()
    material = password.encode("utf-8")
    if device_id:
        material = material + b"::" + device_id.encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LEN,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(material)


def seal_bytes(plaintext: bytes, password: str, *, device_id: str = "") -> bytes:
    """Return blob: salt(32) || nonce(12) || ciphertext+tag."""
    salt = _get_or_create_salt()
    key = derive_key(password, salt, device_id=device_id)
    nonce = secrets.token_bytes(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return salt + nonce + ct


def open_bytes(blob: bytes, password: str, *, device_id: str = "") -> bytes:
    if len(blob) < 32 + NONCE_LEN + 16:
        raise ValueError("ciphertext too short")
    salt, nonce, ct = blob[:32], blob[32 : 32 + NONCE_LEN], blob[32 + NONCE_LEN :]
    key = derive_key(password, salt, device_id=device_id)
    return AESGCM(key).decrypt(nonce, ct, None)


def seal_json(obj: Any, password: str, *, device_id: str = "") -> bytes:
    return seal_bytes(json.dumps(obj, separators=(",", ":")).encode(), password, device_id=device_id)


def open_json(blob: bytes, password: str, *, device_id: str = "") -> Any:
    return json.loads(open_bytes(blob, password, device_id=device_id))


def write_sealed_file(path: Path, plaintext: bytes, password: str, *, device_id: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(seal_bytes(plaintext, password, device_id=device_id))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_sealed_file(path: Path, password: str, *, device_id: str = "") -> bytes:
    return open_bytes(path.read_bytes(), password, device_id=device_id)


@dataclass
class SealResult:
    path: Path
    size: int
    ok: bool
