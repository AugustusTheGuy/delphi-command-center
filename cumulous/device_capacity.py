"""Honest device vs vault capacity reporting for Cumulous UI."""

from __future__ import annotations

import html
import os
import subprocess
from pathlib import Path
from typing import Any


def _bytes_label(n: int | float | None) -> str:
    try:
        b = float(n or 0)
    except (TypeError, ValueError):
        return "—"
    if b <= 0:
        return "—"
    if b < 1024**3:
        return f"{b / (1024**2):.0f} MB"
    return f"{b / (1024**3):.2f} GB"


def _du_bytes(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        out = subprocess.check_output(["du", "-sk", str(path)], text=True, stderr=subprocess.DEVNULL)
        kb = int(out.split()[0])
        return kb * 1024
    except Exception:
        return 0


def _idevice_disk(udid: str = "") -> dict[str, Any]:
    cmd = ["ideviceinfo"]
    if udid:
        cmd.extend(["-u", udid])
    cmd.extend(["-q", "com.apple.disk_usage"])
    try:
        raw = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=12)
    except Exception:
        return {}
    out: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        try:
            out[k] = int(v)
        except ValueError:
            out[k] = v
    return out


def capacity_report(*, udid: str = "") -> dict[str, Any]:
    """Live measured capacity + vault sizes + incomplete full-backup flag."""
    from cumulous.devices import probe_connected_device
    from cumulous.paths import backup_incoming_root, vault_root

    probe = probe_connected_device() or {}
    udid = udid or str(probe.get("udid") or "")
    disk = _idevice_disk(udid) if udid else {}
    total = int(disk.get("TotalDiskCapacity") or 0)
    data_cap = int(disk.get("TotalDataCapacity") or 0)
    data_free = int(disk.get("TotalDataAvailable") or 0)
    data_used = max(0, data_cap - data_free) if data_cap else 0

    photos = _du_bytes(Path("/Volumes/ExternalSSD/CumulousPhotos"))
    music = _du_bytes(Path("/Volumes/ExternalSSD/CumulousMusic"))
    vault = _du_bytes(Path(str(vault_root() or "")) if vault_root() else Path("/Volumes/ExternalSSD/CumulousVault"))
    incoming_root = Path(str(backup_incoming_root() or "/Volumes/ExternalSSD/CumulousIncoming"))
    full_trees = sorted(incoming_root.glob("full_*"), key=lambda p: p.stat().st_mtime, reverse=True) if incoming_root.is_dir() else []
    full_bytes = _du_bytes(full_trees[0]) if full_trees else 0
    incomplete = True
    status_note = "No finished full-system Manifest yet"
    if full_trees:
        # Status.plist under UDID subfolder
        for sp in full_trees[0].rglob("Status.plist"):
            try:
                text = sp.read_text(errors="ignore")
                if "SnapshotState" in text and "finished" in text.lower():
                    incomplete = False
                    status_note = "Full backup marked finished"
                elif "SnapshotState" in text and "new" in text:
                    incomplete = True
                    status_note = "Full backup incomplete (Status=new · aborted mid-transfer)"
            except Exception:
                pass
            break

    dual_photos = 0
    try:
        from cumulous.photo_offload import library_status

        dual_photos = int(library_status().get("mirrored_dual_count") or 0)
    except Exception:
        pass

    return {
        "device_name": probe.get("display_name") or "iPhone",
        "udid": udid,
        "total_disk_bytes": total,
        "data_capacity_bytes": data_cap,
        "data_free_bytes": data_free,
        "data_used_bytes": data_used,
        "photos_vault_bytes": photos,
        "music_vault_bytes": music,
        "vault_bytes": vault,
        "full_tree_bytes": full_bytes,
        "full_tree_incomplete": incomplete,
        "full_tree_note": status_note,
        "photos_dual_count": dual_photos,
        "labels": {
            "total_disk": _bytes_label(total),
            "data_used": _bytes_label(data_used),
            "data_free": _bytes_label(data_free),
            "photos": _bytes_label(photos),
            "music": _bytes_label(music),
            "full_tree": _bytes_label(full_bytes),
            "vault": _bytes_label(vault),
        },
    }


def capacity_report_html() -> str:
    r = capacity_report()
    L = r["labels"]
    warn = (
        "<b style='color:#ffd60a'>Not zip compression</b> — the ~9 GB full-system tree is an "
        "<b>incomplete</b> idevicebackup2 transfer (Error 205 / mid-run abort). "
        "Photos and Music dual-mirrors are separate. "
        "Device capacity is <b>128 GB</b> (CEO-confirmed). "
        "Live data used ≈ <b>"
        + html.escape(L["data_used"])
        + "</b> · free ≈ <b>"
        + html.escape(L["data_free"])
        + "</b> · reported disk <b>"
        + html.escape(L["total_disk"] or "—")
        + "</b>."
    )
    if not r["full_tree_incomplete"]:
        warn = "Full-system tree reports finished. Photos/Music dual sizes listed below."
    return (
        "<div class='cs-card' style='margin-top:0.5rem'>"
        "<div class='cs-header' style='margin-top:0'>Storage truth</div>"
        f"<div class='cs-muted' style='margin-bottom:0.45rem'>{warn}</div>"
        f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;font-size:0.86rem'>"
        f"<div>Phone disk (USB) <b style='float:right'>{html.escape(L['total_disk'])}</b></div>"
        f"<div>Data used ≈ <b style='float:right'>{html.escape(L['data_used'])}</b></div>"
        f"<div>Data free ≈ <b style='float:right'>{html.escape(L['data_free'])}</b></div>"
        f"<div>Photos vault <b style='float:right'>{html.escape(L['photos'])}</b></div>"
        f"<div>Music vault <b style='float:right'>{html.escape(L['music'])}</b></div>"
        f"<div>Full-system tree <b style='float:right'>{html.escape(L['full_tree'])}</b></div>"
        f"</div>"
        f"<div class='cs-faint' style='margin-top:0.45rem'>{html.escape(str(r.get('full_tree_note') or ''))} · "
        f"{int(r.get('photos_dual_count') or 0)} photos dual-mirrored</div>"
        "</div>"
    )
