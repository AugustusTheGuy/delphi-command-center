"""Automated first-run: BEARACCOUNT + personal user + device + CEOOVERRIDE (local only)."""

from __future__ import annotations

import json
import os
import secrets
import string
from pathlib import Path

from cumulous.auth import (
    bearaccount_exists,
    create_bearaccount,
    create_user,
    load_secrets,
    register_ceo_override_devices,
)
from cumulous.ceo_override import write_ceo_override_md
from cumulous.devices import register_device
from cumulous.paths import ensure_internal, internal_root
from cumulous.progressive_backup import create_generation
from cumulous.device_bridge import fingerprint_files, verify_against_generation
from cumulous.totp_2fa import load_secret, provisioning_uri


def _gen_password(n: int = 14) -> str:
    # Meets policy: 8+, number, symbol
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if any(c.isdigit() for c in pw) and any(c in "!@#$%&*" for c in pw):
            return pw


def run_first_setup(
    *,
    bear_username: str = "BEARACCOUNT",
    personal_username: str = "DelphiBEAR",
    device_id: str = "iphone-14-pro-max",
    device_display: str = "iPhone 14 Pro Max",
    force: bool = False,
) -> dict:
    ensure_internal()
    report: dict = {"steps": [], "local_credentials_file": str(internal_root() / "FIRST_RUN_CREDENTIALS.txt")}
    creds: dict = {}

    if bearaccount_exists() and not force:
        report["steps"].append({"step": "bearaccount", "status": "already_exists"})
        secrets_data = load_secrets()
        report["bearaccount_username"] = secrets_data.get("bearaccount_username", bear_username)
    else:
        bear_pw = os.environ.get("CUMULOUS_BEAR_PASSWORD") or _gen_password()
        res = create_bearaccount(bear_username, bear_pw)
        creds["bearaccount"] = {
            "username": bear_username,
            "password": bear_pw,
            "totp_secret": res["totp_secret"],
            "otpauth_uri": res["otpauth_uri"],
        }
        report["steps"].append({"step": "bearaccount", "status": "created", "totp_enrolled": True})

    # Personal user
    data = load_secrets()
    usernames = {u["username"] for u in data.get("users", [])}
    if personal_username in usernames and not force:
        report["steps"].append({"step": "personal_user", "status": "already_exists", "username": personal_username})
    else:
        if personal_username in usernames:
            report["steps"].append({"step": "personal_user", "status": "skipped_exists"})
        else:
            person_pw = os.environ.get("CUMULOUS_USER_PASSWORD") or _gen_password()
            create_user(personal_username, person_pw, device_ids=[device_id])
            creds["personal"] = {"username": personal_username, "password": person_pw}
            report["steps"].append({"step": "personal_user", "status": "created", "username": personal_username})

    # Devices: personal + CEO override flags
    register_device(
        device_id,
        display_name=device_display,
        owner_username=personal_username,
        model="iPhone 14 Pro Max",
        is_ceo_override=False,
    )
    register_device(
        f"{device_id}-ceo-link",
        display_name=f"{device_display} (CEO link)",
        owner_username=bear_username if bearaccount_exists() else "BEARACCOUNT",
        model="iPhone 14 Pro Max",
        is_ceo_override=True,
    )
    register_ceo_override_devices([f"{device_id}-ceo-link"])
    report["steps"].append({"step": "devices", "status": "registered", "device_id": device_id})

    # CEOOVERRIDE.md
    path = write_ceo_override_md(port=8765)
    report["steps"].append({"step": "ceo_override_md", "status": "written", "path": str(path)})

    # Seed first progressive generation (placeholder until phone syncs real media)
    vault_pw = os.environ.get("CUMULOUS_VAULT_PASSWORD") or (
        creds.get("personal", {}).get("password")
        or creds.get("bearaccount", {}).get("password")
        or _gen_password()
    )
    if "vault_password" not in creds and "personal" in creds:
        creds["vault_password_note"] = "Use personal account password for vault demos unless you set CUMULOUS_VAULT_PASSWORD"
    seed_files = {
        "README.txt": b"Cumulous first generation placeholder. Replace via phone backup / companion ingest.",
        "device.json": json.dumps({"device_id": device_id, "display": device_display}).encode(),
    }
    t0 = fingerprint_files(seed_files)
    # Prefer personal password for vault if we just created it
    pw_for_vault = (
        creds.get("personal", {}).get("password")
        or os.environ.get("CUMULOUS_VAULT_PASSWORD")
        or vault_pw
    )
    gen = create_generation(
        device_id,
        seed_files,
        pw_for_vault,
        categories=["files", "notes"],
        mode="standard",
    )
    if gen.get("status") == "ok":
        ver = verify_against_generation(device_id, gen["head"], t0)
        report["steps"].append(
            {
                "step": "first_generation",
                "status": gen["status"],
                "head": gen.get("head"),
                "verification": ver.get("status"),
            }
        )
        creds["vault_password"] = pw_for_vault
    else:
        report["steps"].append({"step": "first_generation", "status": gen.get("status"), "detail": gen})

    secret = load_secret()
    report["totp_enrolled"] = bool(secret)
    if secret and "bearaccount" not in creds:
        report["otpauth_uri_if_already_enrolled"] = provisioning_uri(secret)

    # Write credentials ONLY under ~/.cumulous (never git)
    if creds:
        out = internal_root() / "FIRST_RUN_CREDENTIALS.txt"
        lines = [
            "CUMULOUS FIRST-RUN CREDENTIALS — KEEP PRIVATE — DO NOT COMMIT",
            "Generated for local setup only. Change passwords in the app after first login.",
            "",
        ]
        if "bearaccount" in creds:
            b = creds["bearaccount"]
            lines += [
                f"BEARACCOUNT username: {b['username']}",
                f"BEARACCOUNT password: {b['password']}",
                f"2FA secret (scan once): {b['totp_secret']}",
                f"otpauth URI: {b['otpauth_uri']}",
                "",
            ]
        if "personal" in creds:
            p = creds["personal"]
            lines += [
                f"Personal username: {p['username']}",
                f"Personal password: {p['password']}",
                "",
            ]
        if "vault_password" in creds:
            lines += [f"Vault password (this machine seed): {creds['vault_password']}", ""]
        lines.append(f"Device id: {device_id} ({device_display})")
        out.write_text("\n".join(lines))
        try:
            out.chmod(0o600)
        except OSError:
            pass
        report["credentials_written"] = str(out)

    report["ok"] = True
    return report


def main() -> None:
    import json as _json

    print(_json.dumps(run_first_setup(), indent=2))


if __name__ == "__main__":
    main()
