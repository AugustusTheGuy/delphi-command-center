"""Local session for Delphi: Home Control.

The dashboard opens without a password. The Swift shell keeps it on 127.0.0.1.
"""

import json
import os
import secrets
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
AUTH_FILE = DATA_DIR / "users.json"
SECRET_FILE = DATA_DIR / ".auth_secret"
DEFAULT_ADMIN_USER = "DelphiBEAR"


def load_users() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not AUTH_FILE.exists():
        return {"users": []}
    return json.loads(AUTH_FILE.read_text())


def save_users(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(data, indent=2))
    os.chmod(AUTH_FILE, 0o600)


def ensure_default_user() -> None:
    data = load_users()
    users = data.get("users") or []
    if not users:
        users = [{"username": DEFAULT_ADMIN_USER, "role": "admin"}]
    changed = not data.get("users")
    for user in users:
        if "password_hash" in user:
            user.pop("password_hash", None)
            changed = True
    if changed:
        data["users"] = users
        save_users(data)
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32))
        os.chmod(SECRET_FILE, 0o600)


def authenticate(username: str, password: str) -> bool:
    """Local sessions match the username. The password is ignored."""
    del password
    ensure_default_user()
    data = load_users()
    return any(user.get("username") == username for user in data.get("users", []))


def change_password(username: str, new_password: str) -> bool:
    del username, new_password
    return False
