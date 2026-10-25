"""Always-latest Cumulous version + icon sync (Mac launchers + iOS webclip).

On every app load:
  - Serve /app/version.json with version, icon etag, splash duration hint
  - Mac Desktop/Dock apps re-sync icns from repo assets via sync_cumulous_launcher.sh
  - iOS Web Clip re-issued when icon hash changes so Home Screen shows newest art
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ICONS = ASSETS / "icons"
VERSION_FILE = ROOT / "VERSION"


def package_version() -> str:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.1.0"
    try:
        from cumulous import __version__

        return str(__version__)
    except Exception:
        return "0.1.0"


def icon_paths() -> dict[str, Path]:
    return {
        "mac_png": ICONS / "cumulous_mac_icon.png",
        "mac_icns": ICONS / "Cumulous.icns",
        "ios_png": ICONS / "cumulous_ios_icon.png",
        "appicon_1024": ICONS / "AppIcon-1024.png",
    }


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def icon_manifest() -> dict[str, Any]:
    paths = icon_paths()
    out: dict[str, Any] = {}
    for key, p in paths.items():
        out[key] = {
            "path": str(p),
            "exists": p.is_file(),
            "sha256_16": file_sha256(p),
            "mtime": p.stat().st_mtime if p.is_file() else 0,
            "url": f"/install/icon.png?v={file_sha256(p) or '0'}" if "ios" in key or "appicon" in key or key.endswith("png") else None,
        }
    # Canonical iOS home-screen icon URL always latest
    ios = paths["appicon_1024"] if paths["appicon_1024"].is_file() else paths["ios_png"]
    out["homescreen_icon_url"] = f"/install/icon.png?v={file_sha256(ios) or int(time.time())}"
    return out


def projected_splash_duration_sec(*, cold: bool | None = None) -> float:
    """Scale Delphi Technologies splash to projected load time."""
    # Baseline: Streamlit/API readiness probe
    base = 1.6
    try:
        import urllib.request

        t0 = time.time()
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1.2) as r:
            _ = r.read(64)
        rtt = time.time() - t0
        # Warm API → shorter splash; cold → longer
        base = 1.4 + min(2.5, rtt * 8)
    except Exception:
        base = 2.8  # API not up yet — longer branded load
    if cold is True:
        base = max(base, 2.6)
    if cold is False:
        base = min(base, 2.0)
    return max(1.2, min(base, 4.2))


def device_installs_path() -> Path:
    return ensure_internal() / "device_installs.json"


def load_device_installs() -> dict[str, Any]:
    p = device_installs_path()
    if not p.exists():
        return {"devices": {}, "updated_at": 0}
    try:
        data = json.loads(p.read_text())
        if "devices" not in data:
            data = {"devices": data if isinstance(data, dict) else {}, "updated_at": 0}
        return data
    except Exception:
        return {"devices": {}, "updated_at": 0}


def save_device_installs(data: dict[str, Any]) -> None:
    ensure_internal()
    data["updated_at"] = time.time()
    p = device_installs_path()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def record_device_install(
    *,
    device_id: str,
    version: str = "",
    platform: str = "ios",
    source: str = "app_launch",
    display_name: str = "",
    preference: str = "",
    user_agent: str = "",
) -> dict[str, Any]:
    """Persistently record which Cumulous version is installed on a device.

    Called on every /app launch, install accept, and version check so iOS
    stays aligned with package VERSION.
    """
    did = (device_id or "").strip() or "unknown"
    ver = (version or package_version()).strip()
    data = load_device_installs()
    devices = data.setdefault("devices", {})
    prev = dict(devices.get(did) or {})
    history = list(prev.get("version_history") or [])
    if not history or history[-1].get("version") != ver:
        history.append({"version": ver, "at": time.time(), "source": source})
    history = history[-40:]
    rec = {
        **prev,
        "device_id": did,
        "display_name": display_name or prev.get("display_name") or did,
        "version": ver,
        "package_version": package_version(),
        "up_to_date": ver == package_version(),
        "platform": platform or prev.get("platform") or "ios",
        "source": source,
        "preference": preference or prev.get("preference") or "",
        "user_agent": (user_agent or prev.get("user_agent") or "")[:240],
        "first_installed_at": prev.get("first_installed_at") or time.time(),
        "last_seen_at": time.time(),
        "install_count": int(prev.get("install_count") or 0) + (1 if source.startswith("install") else 0),
        "launch_count": int(prev.get("launch_count") or 0) + (1 if source in ("app_launch", "version_check", "shell_boot") else 0),
        "version_history": history,
    }
    if source.startswith("install") and not prev.get("install_count"):
        rec["install_count"] = max(1, int(rec.get("install_count") or 0))
    devices[did] = rec
    save_device_installs(data)
    return rec


def list_device_installs() -> list[dict[str, Any]]:
    data = load_device_installs()
    rows = list((data.get("devices") or {}).values())
    rows.sort(key=lambda r: float(r.get("last_seen_at") or 0), reverse=True)
    return rows


def version_payload() -> dict[str, Any]:
    ver = package_version()
    icons = icon_manifest()
    try:
        from cumulous.install_invite import best_app_url, best_portal_url

        install_url = best_portal_url()
        app_url = best_app_url()
    except Exception:
        install_url = "http://127.0.0.1:8765/install"
        app_url = "http://127.0.0.1:8765/app/"
    return {
        "product": "Cumulous",
        "org": "Delphi Technologies",
        "org_legal": "Delphi FinTech LLC",
        "version": ver,
        "build_time": time.time(),
        "icons": icons,
        "splash": {
            "title": "Delphi Technologies",
            "subtitle": "Cumulous",
            "duration_sec": projected_splash_duration_sec(),
            "ios": "fullscreen",
            "mac": "medium_borderless_centered",
        },
        "install": {
            "url": install_url,
            "app_url": app_url,
            "webclip_url": "/install/webclip.mobileconfig",
            "always_latest": True,
        },
        "update": {
            "always_check_on_launch": True,
            "mac_sync_script": "scripts/sync_cumulous_launcher.sh",
            "ios_icon_url": icons.get("homescreen_icon_url"),
            "register_endpoint": "/install/register",
            "min_supported": "0.2.0",
        },
        "devices_installed": [
            {
                "device_id": r.get("device_id"),
                "display_name": r.get("display_name"),
                "version": r.get("version"),
                "up_to_date": r.get("up_to_date"),
                "last_seen_at": r.get("last_seen_at"),
            }
            for r in list_device_installs()[:20]
        ],
    }


def sync_mac_launchers(*, quiet: bool = True) -> dict[str, Any]:
    """Re-apply latest icon + CFBundleVersion onto Desktop/Applications Cumulous.app."""
    script = ROOT.parents[0] / "scripts" / "sync_cumulous_launcher.sh"
    if not script.is_file():
        return {"ok": False, "error": "sync_script_missing"}
    try:
        args = [str(script)]
        if quiet:
            args.append("--quiet")
        cp = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
        return {
            "ok": cp.returncode == 0,
            "version": package_version(),
            "stdout": (cp.stdout or "")[:200],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


def ensure_ios_webclip_latest() -> dict[str, Any]:
    """Rewrite Web Clip profile when icon hash changes so Home Screen icon updates on reinstall."""
    state_path = ensure_internal() / "launcher_icon_state.json"
    icons = icon_manifest()
    current = icons.get("homescreen_icon_url") or ""
    prev = ""
    if state_path.exists():
        try:
            prev = json.loads(state_path.read_text()).get("homescreen_icon_url") or ""
        except Exception:
            prev = ""
    changed = current != prev
    if changed:
        try:
            from cumulous.install_invite import write_webclip_profile

            path = write_webclip_profile()
            state_path.write_text(json.dumps({"homescreen_icon_url": current, "updated_at": time.time()}, indent=2))
            return {"ok": True, "changed": True, "profile": str(path), "icon_url": current}
        except Exception as e:
            return {"ok": False, "changed": True, "error": str(e)[:160]}
    return {"ok": True, "changed": False, "icon_url": current}


def on_app_launch() -> dict[str, Any]:
    """Call at every Cumulous load (Mac Streamlit + iOS shell)."""
    mac = sync_mac_launchers(quiet=True)
    ios = ensure_ios_webclip_latest()
    payload = version_payload()
    payload["launch_sync"] = {"mac": mac, "ios_webclip": ios}
    return payload
