"""Secure local backup + restore/view on Mac Mini."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from cumulous.action_status import set_status
from cumulous.companion import collect_files, encrypt_ingest
from cumulous.device_bridge import fingerprint_files, verify_against_generation
from cumulous.devices import probe_connected_device, register_device
from cumulous.paths import backup_incoming_root, device_dir, restore_export_root, vault_root
from cumulous.progressive_backup import create_generation, current_head, restore_generation


def load_vault_password() -> str | None:
    """Read vault password from local FIRST_RUN_CREDENTIALS only (never log)."""
    env = os.environ.get("CUMULOUS_VAULT_PASSWORD")
    if env:
        return env
    from cumulous.paths import internal_root

    p = internal_root() / "FIRST_RUN_CREDENTIALS.txt"
    if not p.exists():
        return None
    text = p.read_text(errors="replace")
    for line in text.splitlines():
        if "Vault password" in line or line.lower().startswith("vault"):
            if ":" in line:
                return line.split(":", 1)[1].strip()
    # fallback: Personal password line
    for line in text.splitlines():
        if "Personal password" in line and ":" in line:
            return line.split(":", 1)[1].strip()
    return None


def device_identity_snapshot(udid: str | None = None) -> dict[str, bytes]:
    """Collect identity + status files for progressive vault (always encrypted)."""
    files: dict[str, bytes] = {}
    probe = probe_connected_device()
    meta = {
        "captured_at": time.time(),
        "probe": probe,
        "host": os.uname().nodename if hasattr(os, "uname") else "mac",
        "product": "Cumulous",
    }
    files["cumulous/device_meta.json"] = json.dumps(meta, indent=2).encode()
    if not probe and not udid:
        return files

    uid = udid or (probe or {}).get("udid") or ""
    keys = [
        "DeviceName",
        "ProductType",
        "ProductVersion",
        "BuildVersion",
        "SerialNumber",
        "UniqueDeviceID",
        "InternationalMobileEquipmentIdentity",
        "PhoneNumber",
        "WiFiAddress",
        "BluetoothAddress",
        "HardwareModel",
        "DeviceClass",
        "TimeZone",
    ]
    info: dict[str, str] = {}
    for k in keys:
        try:
            args = ["ideviceinfo", "-k", k]
            if uid:
                args = ["ideviceinfo", "-u", uid, "-k", k]
            cp = subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)
            val = (cp.stdout or "").strip()
            if val:
                info[k] = val
        except Exception:
            continue
    files["cumulous/ideviceinfo.json"] = json.dumps(info, indent=2).encode()
    files["cumulous/README.txt"] = (
        "Cumulous encrypted progressive vault snapshot.\n"
        "Includes device identity. Full system backup (idevicebackup2) is stored under "
        "CumulousIncoming when run, then ingested as file blobs.\n"
    ).encode()
    return files


def secure_backup_device(
    device_id: str,
    *,
    password: str | None = None,
    apple_account_id: str = "",
    display_name: str = "",
    run_full_idevice: bool = True,
    action_id: str = "backup_device",
) -> dict[str, Any]:
    """Encrypt progressive vault for device; optionally pull idevicebackup2 tree."""
    set_status(action_id, "running", message="Starting secure backup…")
    password = password or load_vault_password()
    if not password:
        set_status(action_id, "error", message="No vault password on this Mac.")
        return {"ok": False, "error": "no_vault_password"}

    probe = probe_connected_device()
    udid = (probe or {}).get("udid") or ""
    name = display_name or (probe or {}).get("display_name") or device_id

    if apple_account_id:
        register_device(
            device_id,
            display_name=name,
            owner_username=apple_account_id,
            model=(probe or {}).get("model") or "",
            is_ceo_override=True,
            udid=udid or (probe or {}).get("udid") or "",
            imei=(probe or {}).get("imei") or "",
            apple_account_id=apple_account_id,
        )
        from cumulous.apple_accounts import attach_device_to_account

        attach_device_to_account(apple_account_id, device_id)

    files = device_identity_snapshot(udid or None)
    full_report: dict[str, Any] = {"identity_files": len(files)}

    if run_full_idevice and udid and shutil.which("idevicebackup2"):
        set_status(action_id, "running", message="Pulling system backup from phone (unlock + keep awake)…")
        incoming = backup_incoming_root() / f"full_{device_id}_{int(time.time())}"
        incoming.mkdir(parents=True, exist_ok=True)
        try:
            # Unencrypted device backup into local folder, then we seal into vault.
            # Phone must be unlocked; passcode prompt may appear on device.
            cp = subprocess.run(
                ["idevicebackup2", "-u", udid, "backup", "--full", str(incoming)],
                capture_output=True,
                text=True,
                timeout=7200,
                check=False,
            )
            combined = ((cp.stderr or "") + "\n" + (cp.stdout or "")).strip()
            full_report["idevicebackup2_rc"] = cp.returncode
            full_report["idevicebackup2_dir"] = str(incoming)
            if "ErrorCode 208" in combined or "Device locked" in combined:
                full_report["idevicebackup2_err"] = (
                    "Phone is locked. Unlock ROB IPHONE (2), keep the screen on, then run Backup again."
                )
            elif cp.returncode == 0 or any(p.is_file() for p in incoming.rglob("*")):
                more = collect_files(incoming, limit=8000)
                for rel, data in more.items():
                    files[f"idevicebackup2/{rel}"] = data
                full_report["idevice_file_count"] = len(more)
                if cp.returncode != 0 and not more:
                    full_report["idevicebackup2_err"] = combined[:500] or f"exit {cp.returncode}"
            else:
                full_report["idevicebackup2_err"] = combined[:500] or f"exit {cp.returncode}"
        except subprocess.TimeoutExpired:
            full_report["idevicebackup2_err"] = "timeout — keep phone unlocked and retry"
        except Exception as e:
            full_report["idevicebackup2_err"] = str(e)[:300]

    set_status(action_id, "running", message="Encrypting into Cumulous vault…")
    t0 = fingerprint_files(files)
    result = create_generation(
        device_id,
        files,
        password,
        mode="persistent",
        categories=["identity", "sms", "notes", "files", "system_backup"],
    )
    if result.get("status") in ("ok", "up_to_date"):
        if result.get("status") == "ok":
            result["verification"] = verify_against_generation(device_id, result["head"], t0)
        result["ok"] = True
        result["vault"] = str(vault_root())
        result["file_count"] = len(files)
        result["full"] = full_report
        set_status(
            action_id,
            "ok",
            message=f"Backup complete · {name}",
            detail=f"{len(files)} sealed items · {result.get('head') or current_head(device_id)}",
        )
    else:
        result["ok"] = False
        set_status(action_id, "error", message="Backup failed", detail=str(result)[:200])
    return result


def restore_to_mac(
    device_id: str,
    gen_id: str,
    *,
    password: str | None = None,
    action_id: str = "restore_device",
) -> dict[str, Any]:
    """Decrypt generation onto Mac Mini under CumulousRestore for viewing."""
    set_status(action_id, "running", message="Decrypting backup onto this Mac…")
    password = password or load_vault_password()
    if not password:
        set_status(action_id, "error", message="No vault password.")
        return {"ok": False, "error": "no_vault_password"}
    try:
        files = restore_generation(device_id, gen_id, password)
    except Exception as e:
        set_status(action_id, "error", message="Could not open backup", detail=str(e)[:200])
        return {"ok": False, "error": str(e)}

    safe = re.sub(r"[^\w.\-]+", "_", device_id)[:80]
    dest = restore_export_root() / safe / gen_id
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    for rel, data in files.items():
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        written += 1
    # open Finder
    try:
        subprocess.run(["open", str(dest)], check=False, timeout=5)
    except Exception:
        pass
    set_status(
        action_id,
        "ok",
        message="Restored on this Mac",
        detail=f"{written} files · {dest}",
    )
    return {"ok": True, "path": str(dest), "file_count": written, "gen_id": gen_id}


def list_device_backup_status(device_id: str) -> dict:
    head = current_head(device_id)
    ddir = device_dir(device_id)
    gens = list((ddir / "generations").glob("*.manifest.json")) if (ddir / "generations").is_dir() else []
    return {
        "device_id": device_id,
        "backed_up": head is not None,
        "head": head,
        "generation_count": len(gens),
        "vault_path": str(ddir),
    }
