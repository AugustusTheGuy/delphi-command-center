"""Apple Account → devices model (no multi-user logins).

Apple Account identity is scraped from this Mac's signed-in iCloud account when
possible (MobileMeAccounts). Full iCloud device fleets are NOT available via
public Apple APIs — Cumulous unions: scraped Mac Apple ID + USB + paired +
registered devices under that account.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any

from cumulous.paths import (
    apple_accounts_file,
    ensure_internal,
    secrets_2x_file,
)
from cumulous.totp_2fa import generate_secret, provisioning_uri, verify_totp


def _load_accounts() -> dict:
    ensure_internal()
    p = apple_accounts_file()
    if not p.exists():
        return {"accounts": [], "mac_mini_device_id": "mac-mini-local"}
    raw = p.read_text()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Tolerate trailing garbage (extra braces) from prior writes
        try:
            data, _end = json.JSONDecoder().raw_decode(raw)
            if isinstance(data, dict):
                _save_accounts(data)
                return data
        except Exception:
            pass
        return {"accounts": [], "mac_mini_device_id": "mac-mini-local"}


def _save_accounts(data: dict) -> None:
    ensure_internal()
    p = apple_accounts_file()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def _load_2x() -> dict:
    ensure_internal()
    p = secrets_2x_file()
    if not p.exists():
        return {"accounts": {}, "updated_at": time.time()}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"accounts": {}, "updated_at": time.time()}


def _save_2x(data: dict) -> None:
    ensure_internal()
    p = secrets_2x_file()
    data["updated_at"] = time.time()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def scrape_mac_apple_accounts() -> list[dict]:
    """Best-effort scrape of Apple IDs signed into this Mac (local only)."""
    found: list[dict] = []
    try:
        cp = subprocess.run(
            ["defaults", "read", "MobileMeAccounts"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        text = cp.stdout or ""
    except Exception:
        return found

    # AccountID = "email@…"; DisplayName = "…"
    ids = re.findall(r'AccountID\s*=\s*"([^"]+)"', text)
    names = re.findall(r'DisplayName\s*=\s*"([^"]+)"', text)
    for i, account_id in enumerate(ids):
        email = account_id.strip()
        if not email or "@" not in email:
            continue
        display = names[i] if i < len(names) else email
        found.append(
            {
                "apple_id": email.lower(),
                "display_name": display,
                "source": "mobileme_mac",
                "verified": True,
                "scraped_at": time.time(),
            }
        )
    # de-dupe
    seen: set[str] = set()
    out: list[dict] = []
    for a in found:
        if a["apple_id"] not in seen:
            seen.add(a["apple_id"])
            out.append(a)
    return out


def ensure_account(apple_id: str, *, display_name: str = "", verified: bool = False, source: str = "manual") -> dict:
    apple_id = (apple_id or "").strip().lower()
    if not apple_id:
        raise ValueError("Apple ID required")
    data = _load_accounts()
    for a in data["accounts"]:
        if a.get("apple_id") == apple_id:
            if display_name:
                a["display_name"] = display_name
            if verified:
                a["verified"] = True
            if source:
                a["source"] = source
            a["updated_at"] = time.time()
            _save_accounts(data)
            return a
    rec = {
        "apple_id": apple_id,
        "display_name": display_name or apple_id,
        "verified": verified,
        "source": source,
        "device_ids": [],
        "is_ceo": False,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    data["accounts"].append(rec)
    _save_accounts(data)
    # One 2FA secret per Apple Account
    ensure_account_2fa(apple_id)
    return rec


def list_accounts() -> list[dict]:
    return list(_load_accounts().get("accounts") or [])


def get_account(apple_id: str) -> dict | None:
    apple_id = (apple_id or "").strip().lower()
    for a in list_accounts():
        if a.get("apple_id") == apple_id:
            return a
    return None


def mark_ceo_account(apple_id: str, is_ceo: bool = True) -> None:
    data = _load_accounts()
    for a in data["accounts"]:
        if a.get("apple_id") == (apple_id or "").strip().lower():
            a["is_ceo"] = is_ceo
            a["updated_at"] = time.time()
            _save_accounts(data)
            return


def attach_device_to_account(apple_id: str, device_id: str) -> None:
    apple_id = (apple_id or "").strip().lower()
    ensure_account(apple_id)
    data = _load_accounts()
    for a in data["accounts"]:
        if a.get("apple_id") == apple_id:
            ids = list(a.get("device_ids") or [])
            if device_id and device_id not in ids:
                ids.append(device_id)
            a["device_ids"] = ids
            a["updated_at"] = time.time()
            _save_accounts(data)
            return


def devices_for_apple_account(apple_id: str) -> list[str]:
    from cumulous.devices import load_devices

    apple_id = (apple_id or "").strip().lower()
    ids: list[str] = []
    acc = get_account(apple_id)
    if acc:
        ids.extend(acc.get("device_ids") or [])
    for d in load_devices().get("devices") or []:
        if (d.get("apple_account_id") or "").lower() == apple_id:
            did = d.get("device_id")
            if did and did not in ids:
                ids.append(did)
    return ids


def ceo_apple_account_ids() -> list[str]:
    return [a["apple_id"] for a in list_accounts() if a.get("is_ceo")]


def ensure_account_2fa(apple_id: str) -> dict:
    """One TOTP secret per Apple Account, stored only in local 2xsecrets (CEO-readable)."""
    apple_id = (apple_id or "").strip().lower()
    data = _load_2x()
    accounts = data.setdefault("accounts", {})
    if apple_id in accounts and accounts[apple_id].get("totp_secret"):
        secret = accounts[apple_id]["totp_secret"]
        return {
            "apple_id": apple_id,
            "totp_secret": secret,
            "otpauth_uri": provisioning_uri(secret, account_name=apple_id),
            "created": False,
        }
    secret = generate_secret()
    accounts[apple_id] = {
        "totp_secret": secret,
        "created_at": time.time(),
        "display": apple_id,
    }
    _save_2x(data)
    return {
        "apple_id": apple_id,
        "totp_secret": secret,
        "otpauth_uri": provisioning_uri(secret, account_name=apple_id),
        "created": True,
    }


def get_account_2fa_secret(apple_id: str) -> str | None:
    apple_id = (apple_id or "").strip().lower()
    data = _load_2x()
    rec = (data.get("accounts") or {}).get(apple_id) or {}
    return rec.get("totp_secret")


def verify_account_2fa(apple_id: str, code: str) -> bool:
    secret = get_account_2fa_secret(apple_id)
    if not secret:
        # bootstrap if missing
        ensure_account_2fa(apple_id)
        secret = get_account_2fa_secret(apple_id)
    return verify_totp(secret or "", code)


def read_2xsecrets_for_ceo() -> dict:
    """Full 2xsecrets payload — only surface in CEO Override UI, never git."""
    return _load_2x()


def sync_scraped_accounts(*, mark_first_as_ceo: bool = True) -> list[dict]:
    """Scrape Mac Apple IDs and upsert into registry."""
    scraped = scrape_mac_apple_accounts()
    out = []
    for i, s in enumerate(scraped):
        rec = ensure_account(
            s["apple_id"],
            display_name=s.get("display_name") or "",
            verified=True,
            source=s.get("source") or "mobileme_mac",
        )
        if mark_first_as_ceo and i == 0:
            mark_ceo_account(s["apple_id"], True)
        out.append(rec)
    return out


def migrate_devices_to_primary_apple_account() -> dict[str, Any]:
    """Attach existing registered devices to primary scraped Apple Account."""
    from cumulous.devices import load_devices, save_devices

    scraped = sync_scraped_accounts(mark_first_as_ceo=True)
    primary = scraped[0]["apple_id"] if scraped else None
    if not primary:
        return {"ok": False, "reason": "no_mac_apple_id"}

    data = load_devices()
    changed = 0
    for d in data.get("devices") or []:
        if not d.get("apple_account_id"):
            d["apple_account_id"] = primary
            d["owner_username"] = primary  # legacy field retained as alias
            changed += 1
        attach_device_to_account(d.get("apple_account_id") or primary, d["device_id"])
        if d.get("is_ceo_override"):
            mark_ceo_account(d.get("apple_account_id") or primary, True)
    # Always register this Mac Mini under CEO apple account for code fan-out
    mac_id = "mac-mini-cumulous"
    from cumulous.devices import register_device

    register_device(
        mac_id,
        display_name="This Mac Mini",
        owner_username=primary,
        model="Mac mini",
        is_ceo_override=True,
        apple_account_id=primary,
    )
    attach_device_to_account(primary, mac_id)
    save_devices(data)
    return {"ok": True, "primary": primary, "devices_updated": changed, "mac_device_id": mac_id}


def catalog_by_apple_account() -> list[dict]:
    """Hierarchy: Apple Account → devices → backup generations summary."""
    from cumulous.devices import load_devices
    from cumulous.progressive_backup import current_head, generation_path
    from cumulous.paths import device_dir

    sync_scraped_accounts(mark_first_as_ceo=True)
    devices = load_devices().get("devices") or []
    by_acct: dict[str, dict] = {}
    for a in list_accounts():
        by_acct[a["apple_id"]] = {
            "apple_id": a["apple_id"],
            "display_name": a.get("display_name") or a["apple_id"],
            "verified": bool(a.get("verified")),
            "is_ceo": bool(a.get("is_ceo")),
            "source": a.get("source") or "",
            "devices": [],
        }
    unassigned = {
        "apple_id": "(unassigned)",
        "display_name": "Unassigned devices",
        "verified": False,
        "is_ceo": False,
        "source": "",
        "devices": [],
    }

    for d in devices:
        aid = (d.get("apple_account_id") or "").lower()
        bucket = by_acct.get(aid) if aid else None
        if not bucket:
            if aid:
                bucket = {
                    "apple_id": aid,
                    "display_name": aid,
                    "verified": False,
                    "is_ceo": False,
                    "source": "device",
                    "devices": [],
                }
                by_acct[aid] = bucket
            else:
                bucket = unassigned

        did = d["device_id"]
        head = current_head(did)
        gens = []
        gdir = device_dir(did) / "generations"
        if gdir.is_dir():
            for gp in sorted(gdir.glob("*.manifest.json"), reverse=True)[:12]:
                try:
                    man = json.loads(gp.read_text())
                    gens.append(
                        {
                            "gen_id": man.get("gen_id"),
                            "created_at": man.get("created_at"),
                            "file_count": man.get("file_count"),
                            "total_bytes": man.get("total_bytes"),
                            "strategy": man.get("strategy"),
                            "is_head": man.get("gen_id") == head,
                        }
                    )
                except Exception:
                    continue
        bucket["devices"].append(
            {
                "device_id": did,
                "display_name": d.get("display_name") or did,
                "model": d.get("model") or "",
                "udid": d.get("udid") or "",
                "imei": d.get("imei") or "",
                "is_ceo_override": bool(d.get("is_ceo_override")),
                "backed_up": head is not None,
                "head": head,
                "generations": gens,
            }
        )

    result = list(by_acct.values())
    if unassigned["devices"]:
        result.append(unassigned)
    result.sort(key=lambda x: (not x.get("is_ceo"), x.get("apple_id") or ""))
    return result
