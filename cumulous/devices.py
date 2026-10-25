"""Device registry, multi-layer USB/usbmux detection, and inventory helpers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from cumulous.paths import devices_file, ensure_internal

# Optional injectables for tests
_RUN: Callable[..., subprocess.CompletedProcess] | None = None


def _run(
    args: list[str],
    *,
    timeout: float = 10,
    text: bool = True,
) -> subprocess.CompletedProcess:
    if _RUN is not None:
        return _RUN(args, timeout=timeout, text=text)
    return subprocess.run(
        args,
        capture_output=True,
        text=text,
        timeout=timeout,
        check=False,
    )


def load_devices() -> dict:
    ensure_internal()
    df = devices_file()
    if not df.exists():
        return {"devices": []}
    return json.loads(df.read_text())


def save_devices(data: dict) -> None:
    ensure_internal()
    df = devices_file()
    df.write_text(json.dumps(data, indent=2))
    try:
        df.chmod(0o600)
    except OSError:
        pass


def devices_for_user(username: str) -> list[str]:
    return [d["device_id"] for d in load_devices()["devices"] if d.get("owner_username") == username]


def ceo_override_device_ids() -> list[str]:
    return [d["device_id"] for d in load_devices()["devices"] if d.get("is_ceo_override")]


def registered_devices() -> list[dict]:
    """All devices in the Cumulous registry (copy of records)."""
    return list(load_devices().get("devices") or [])


def list_connected_idevices() -> list[dict]:
    """Best-effort USB inventory via idevice_id if installed."""
    if not shutil.which("idevice_id") and _RUN is None:
        return []
    try:
        cp = _run(["idevice_id", "-l"], timeout=10)
        out = cp.stdout or ""
    except Exception:
        return []
    return [{"device_id": line.strip(), "transport": "usb"} for line in out.splitlines() if line.strip()]


def _ideviceinfo_key(udid: str, key: str) -> str | None:
    if not shutil.which("ideviceinfo") and _RUN is None:
        return None
    try:
        cp = _run(["ideviceinfo", "-u", udid, "-k", key], timeout=8)
        val = (cp.stdout or "").strip()
        return val or None
    except Exception:
        return None


def _usb_apple_products_from_profiler(text: str) -> list[dict]:
    """Parse system_profiler SPUSBDataType for iPhone/iPad product names."""
    found: list[dict] = []
    # Match Product Name lines that mention iPhone/iPad
    for m in re.finditer(
        r"Product Name:\s*(iPhone[^:\n]*|iPad[^:\n]*)",
        text or "",
        re.IGNORECASE,
    ):
        name = m.group(1).strip()
        # Look nearby for Serial Number
        start = max(0, m.start() - 200)
        end = min(len(text), m.end() + 400)
        window = text[start:end]
        serial = None
        sm = re.search(r"Serial Number:\s*(\S+)", window)
        if sm:
            serial = sm.group(1).strip()
        found.append({"product_name": name, "serial": serial, "source": "system_profiler"})
    return found


def _usb_apple_products_from_ioreg(text: str) -> list[dict]:
    """Parse ioreg -p IOUSB for USB Product Name iPhone/iPad."""
    found: list[dict] = []
    for m in re.finditer(
        r'"USB Product Name"\s*=\s*"(iPhone[^"]*|iPad[^"]*)"',
        text or "",
        re.IGNORECASE,
    ):
        found.append({"product_name": m.group(1).strip(), "serial": None, "source": "ioreg"})
    return found


def usb_apple_products_seen() -> list[dict]:
    """macOS USB tree: iPhone/iPad product entries (even before Trust/usbmux)."""
    products: list[dict] = []
    try:
        if shutil.which("system_profiler") or _RUN is not None:
            cp = _run(["system_profiler", "SPUSBDataType"], timeout=25)
            products.extend(_usb_apple_products_from_profiler(cp.stdout or ""))
    except Exception:
        pass
    if products:
        return products
    try:
        if shutil.which("ioreg") or _RUN is not None:
            cp = _run(["ioreg", "-p", "IOUSB", "-l", "-w", "0"], timeout=15)
            products.extend(_usb_apple_products_from_ioreg(cp.stdout or ""))
    except Exception:
        pass
    return products


def list_paired_on_mac() -> list[dict]:
    """Historically paired UDIDs known to this Mac (idevicepair list)."""
    if not shutil.which("idevicepair") and _RUN is None:
        return []
    try:
        cp = _run(["idevicepair", "list"], timeout=12)
        out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    except Exception:
        return []
    pairs: list[dict] = []
    # Formats vary: bare UDID lines, or "UDID - SUCCESS"
    for line in out.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("error"):
            continue
        # 40-char hex UDID (classic) or 24+ with dash
        m = re.search(r"\b([0-9a-fA-F]{24,40})\b", line)
        if m:
            pairs.append({"device_id": m.group(1), "status": "paired", "raw": line})
    # de-dupe
    seen: set[str] = set()
    unique: list[dict] = []
    for p in pairs:
        if p["device_id"] not in seen:
            seen.add(p["device_id"])
            unique.append(p)
    return unique


def attempt_pair(udid: str | None = None) -> dict[str, Any]:
    """Try idevicepair pair / validate for a UDID (or default first device)."""
    if not shutil.which("idevicepair") and _RUN is None:
        return {
            "ok": False,
            "action": "missing_tool",
            "message": "Phone pairing tools are not installed. Use Install phone tools first.",
        }
    args_base = ["idevicepair"]
    if udid:
        args_base.extend(["-u", udid])
    try:
        validate = _run(args_base + ["validate"], timeout=15)
        if validate.returncode == 0 and "success" in ((validate.stdout or "") + (validate.stderr or "")).lower():
            return {"ok": True, "action": "already_paired", "udid": udid or "", "message": "Already trusted/paired."}
        pair = _run(args_base + ["pair"], timeout=30)
        combined = ((pair.stdout or "") + "\n" + (pair.stderr or "")).strip()
        low = combined.lower()
        if pair.returncode == 0 or "success" in low:
            return {"ok": True, "action": "paired", "udid": udid or "", "message": "Pair succeeded. Phone is trusted."}
        if "user denied" in low or "password protected" in low or "lockdownd" in low:
            return {
                "ok": False,
                "action": "trust_needed",
                "udid": udid or "",
                "message": "Unlock the iPhone and tap Trust This Computer, then try again.",
            }
        return {
            "ok": False,
            "action": "failed",
            "udid": udid or "",
            "message": combined[:280] or "Pairing failed. Unlock phone, use a data cable, tap Trust.",
        }
    except Exception as e:
        return {"ok": False, "action": "error", "message": str(e)[:200]}


def probe_connected_device() -> dict | None:
    """Return best identity for the first plugged Apple device (UDID + IMEI when available).

    UDID is the reliable always-present hardware id from libimobiledevice.
    IMEI is preferred when Trust allows ideviceinfo to read it.
    """
    devices = list_connected_idevices()
    if not devices:
        return None
    udid = devices[0]["device_id"]
    imei = _ideviceinfo_key(udid, "InternationalMobileEquipmentIdentity")
    name = _ideviceinfo_key(udid, "DeviceName")
    model = _ideviceinfo_key(udid, "ProductType") or _ideviceinfo_key(udid, "ModelNumber")
    phone = _ideviceinfo_key(udid, "PhoneNumber")
    serial = _ideviceinfo_key(udid, "SerialNumber")
    return {
        "udid": udid,
        "imei": imei,
        "device_id": imei or udid,
        "display_name": name or "Apple Device",
        "model": model or "",
        "phone_number": phone or "",
        "serial": serial or "",
        "transport": "usb",
        "awaiting_trust": imei is None and name is None,
    }


def apple_account_label() -> str:
    """Optional display label from local secrets only (never scraped from Apple)."""
    try:
        from cumulous.auth import load_secrets

        data = load_secrets()
        return str(data.get("apple_account_label") or "").strip()
    except Exception:
        return ""


def set_apple_account_label(label: str) -> None:
    from cumulous.auth import load_secrets, save_secrets

    data = load_secrets()
    data["apple_account_label"] = (label or "").strip()
    save_secrets(data)


def device_inventory(*, user_says_plugged: bool = False) -> dict[str, Any]:
    """Full detection stack for UI: connected, paired, registered, trust/cable flags.

    Detection order:
      1. idevice_id -l          → UDID(s) if usbmuxd path works
      2. system_profiler / ioreg → Product Name iPhone/iPad
      3. idevicepair list       → historically paired UDIDs
      4. Cumulous registry      → registered devices
    """
    connected_raw = list_connected_idevices()
    connected: list[dict] = []
    for c in connected_raw:
        udid = c["device_id"]
        imei = _ideviceinfo_key(udid, "InternationalMobileEquipmentIdentity")
        name = _ideviceinfo_key(udid, "DeviceName")
        model = _ideviceinfo_key(udid, "ProductType") or _ideviceinfo_key(udid, "ModelNumber")
        connected.append(
            {
                "udid": udid,
                "device_id": imei or udid,
                "imei": imei,
                "display_name": name or "Apple Device",
                "model": model or "",
                "transport": "usb",
                "awaiting_trust": imei is None and name is None,
            }
        )

    usb_products = usb_apple_products_seen()
    paired = list_paired_on_mac()
    registered = registered_devices()

    usbmux_seen = len(connected_raw) > 0
    usb_iphone_seen = len(usb_products) > 0
    # USB product visible but no usbmux UDID → unlock / Trust likely needed
    trust_needed = usb_iphone_seen and not usbmux_seen
    # CEO says plugged but macOS never saw an iPhone product or UDID
    cable_or_power_only = bool(user_says_plugged) and not usbmux_seen and not usb_iphone_seen

    # Related = union of registered + paired + connected (dedupe by udid/device_id)
    related: list[dict] = []
    seen_keys: set[str] = set()

    def _add(key: str, rec: dict) -> None:
        if not key or key in seen_keys:
            return
        seen_keys.add(key)
        related.append(rec)

    for c in connected:
        _add(c.get("udid") or c.get("device_id") or "", {**c, "source": "connected"})
    for p in paired:
        _add(p.get("device_id") or "", {**p, "display_name": p.get("display_name") or "Paired on this Mac", "source": "paired_on_mac"})
    for r in registered:
        key = r.get("udid") or r.get("device_id") or ""
        _add(key, {**r, "source": "registered"})

    status_line = "No iPhone on USB"
    if usbmux_seen:
        names = ", ".join(c.get("display_name") or c.get("udid", "")[:8] for c in connected)
        status_line = f"Connected: {names}"
    elif trust_needed:
        prod = usb_products[0].get("product_name") or "iPhone"
        status_line = f"Mac sees {prod} — unlock and tap Trust"
    elif cable_or_power_only:
        status_line = "Mac does not see your iPhone on USB yet"
    elif paired:
        status_line = f"No live USB · {len(paired)} paired on this Mac"
    elif registered:
        status_line = f"No live USB · {len(registered)} registered in Cumulous"

    return {
        "connected": connected,
        "paired_on_mac": paired,
        "registered": registered,
        "related_devices": related,
        "usb_products": usb_products,
        "usb_iphone_seen": usb_iphone_seen,
        "usbmux_seen": usbmux_seen,
        "trust_needed": trust_needed,
        "cable_or_power_only": cable_or_power_only,
        "apple_account_label": apple_account_label(),
        "status_line": status_line,
        "primary_probe": connected[0] if connected else None,
    }


def register_device(
    device_id: str,
    *,
    display_name: str,
    owner_username: str = "",
    model: str = "",
    is_ceo_override: bool = False,
    udid: str = "",
    imei: str = "",
    apple_account_id: str = "",
) -> dict:
    """Register device under Apple Account (preferred) or legacy owner_username."""
    apple_account_id = (apple_account_id or owner_username or "").strip().lower()
    data = load_devices()
    for d in data["devices"]:
        if d["device_id"] == device_id or (udid and d.get("udid") == udid):
            d.update(
                {
                    "display_name": display_name,
                    "owner_username": apple_account_id or owner_username or d.get("owner_username", ""),
                    "apple_account_id": apple_account_id or d.get("apple_account_id", ""),
                    "model": model or d.get("model", ""),
                    "is_ceo_override": is_ceo_override or d.get("is_ceo_override", False),
                    "udid": udid or d.get("udid", ""),
                    "imei": imei or d.get("imei", ""),
                    "updated_at": time.time(),
                }
            )
            save_devices(data)
            return d
    rec = {
        "device_id": device_id,
        "display_name": display_name,
        "owner_username": apple_account_id or owner_username,
        "apple_account_id": apple_account_id,
        "model": model,
        "is_ceo_override": is_ceo_override,
        "udid": udid,
        "imei": imei,
        "created_at": time.time(),
        "updated_at": time.time(),
        "install_invite_pending": True,
    }
    data["devices"].append(rec)
    save_devices(data)
    # New device → auto install push (Home Screen / App Library choice on phone)
    try:
        from cumulous.install_invite import create_invite_for_device

        create_invite_for_device(
            device_id=device_id,
            display_name=display_name,
            apple_account_id=apple_account_id,
            transport="auto",
        )
    except Exception:
        pass
    return rec


def devices_for_apple_account(apple_account_id: str) -> list[str]:
    aid = (apple_account_id or "").strip().lower()
    return [
        d["device_id"]
        for d in load_devices()["devices"]
        if (d.get("apple_account_id") or d.get("owner_username") or "").lower() == aid
    ]
