"""Wi‑Fi / cellular backup channels to this Mac Mini.

USB remains the most reliable path for full idevicebackup2.
Network paths:
  - Wi‑Fi: wireless usbmux (device paired over Wi‑Fi) + FastAPI ingest
  - Cellular / remote: Tailscale or LAN URL → FastAPI progressive upload
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal, vault_root


def local_ip_candidates() -> list[str]:
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        out = subprocess.check_output(["ifconfig"], text=True, timeout=5)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "127.0.0.1" not in line:
                parts = line.split()
                if len(parts) >= 2:
                    ips.append(parts[1])
    except Exception:
        pass
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for ip in ips:
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def tailscale_ip() -> str | None:
    try:
        cp = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        ip = (cp.stdout or "").strip().splitlines()
        return ip[0] if ip else None
    except Exception:
        return None


def backup_endpoints(
    *,
    streamlit_port: int = 8502,
    api_port: int = 8765,
    nextcloud_https_port: int = 8443,
) -> dict[str, Any]:
    lan = local_ip_candidates()
    # Prefer primary LAN (skip common VM/bridge ranges when a real Wi‑Fi IP exists)
    primary = next((h for h in lan if not h.startswith("192.168.234.")), lan[0] if lan else None)
    ts = tailscale_ip()
    return {
        "usb": {"available": True, "note": "Plug in · Trust · best for full system backup"},
        "wifi_lan": {
            "available": bool(lan),
            "hosts": lan,
            "streamlit": [f"http://{h}:{streamlit_port}" for h in lan],
            "api": [f"http://{h}:{api_port}" for h in lan],
            "health": [f"http://{h}:{api_port}/health" for h in lan],
            "install": [f"http://{h}:{api_port}/install" for h in lan],
            "note": "Same Wi‑Fi as Mac Mini. Pair wirelessly after one USB Trust.",
        },
        "nextcloud": {
            # HTTPS only — cleartext host port removed; Caddy TLS on 8443
            "mac_browser_https": f"https://127.0.0.1:{nextcloud_https_port}",
            "phone_https": (
                [f"https://{h}:{nextcloud_https_port}" for h in lan]
                if lan
                else [f"https://127.0.0.1:{nextcloud_https_port}"]
            ),
            "primary_phone_url": (
                f"https://{primary}:{nextcloud_https_port}"
                if primary
                else f"https://127.0.0.1:{nextcloud_https_port}"
            ),
            "require_https": True,
            "note": (
                "All Nextcloud traffic is HTTPS-only (TLS 1.2+). "
                "Phone app → primary_phone_url; trust home cert once. "
                "Cumulous dual-mirror WebDAV uses the same TLS endpoint with pinned cert."
            ),
        },
        "cellular_or_remote": {
            "available": bool(ts),
            "tailscale_ip": ts,
            "streamlit": f"http://{ts}:{streamlit_port}" if ts else None,
            "api": f"http://{ts}:{api_port}" if ts else None,
            "nextcloud_https": f"https://{ts}:{nextcloud_https_port}" if ts else None,
            "note": (
                "Install Tailscale on iPhone + Mac (same account). "
                "Cellular then reaches this Mac Mini over the private mesh."
            ),
        },
        "ingest_path": "/backup/upload",
        "vault": str(vault_root()),
    }


def enable_wifi_sync_hint() -> dict[str, Any]:
    """Document + attempt wireless lockdownd enable if tools present."""
    steps = [
        "Connect iPhone by USB once and tap Trust.",
        "On Mac: keep Cumulous / usbmuxd running.",
        "iPhone and Mac on same Wi‑Fi (or Tailscale for cellular).",
        "Optional Terminal: idevicepair pair && ideviceinfo -n  (network mode).",
    ]
    network_list: list[str] = []
    try:
        cp = subprocess.run(
            ["idevice_id", "-n"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        network_list = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
    except Exception:
        pass
    return {
        "wifi_devices_seen": network_list,
        "steps": steps,
        "ok": True,
    }


def save_network_prefs(prefs: dict) -> Path:
    ensure_internal()
    p = ensure_internal() / "network_backup.json"
    prefs = {**prefs, "updated_at": time.time()}
    p.write_text(json.dumps(prefs, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def load_network_prefs() -> dict:
    p = ensure_internal() / "network_backup.json"
    if not p.exists():
        return {
            "wifi_enabled": True,
            "cellular_enabled": True,
            "prefer_transport": "auto",  # auto | usb | wifi | cellular
        }
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}
