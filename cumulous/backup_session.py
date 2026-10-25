"""Live multi-transport backup sessions with progress, naming, and lock-resilience.

Honesty (Apple platform limits):
  - Full idevicebackup2 system dumps require a trusted pair; when the phone is
    passcode-locked, Apple's mobilebackup2 service often waits or aborts.
  - Cumulous auto-resumes when the device is unlocked again (USB or wireless).
  - The Cumulous iOS app can keep its own screen awake (idle timer off) while
    open during progressive photo upload — it cannot force system lock screen
    off when the user is outside the app (no private API).
  - USB → Wi‑Fi/cellular handoff: full system tree continues over wireless
    usbmux when available; otherwise progressive API ingest continues the same
    session catalog so no data is "lost" when the cable drops.

Naming: ``{Device}-{Kind}-{YYYY-MM-DD}-Backup{N}-Cumulous``
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cumulous.paths import backup_incoming_root, ensure_internal, externalssd_mounted
from cumulous.ux_copy import (
    client_error,
    progress_headline,
    progress_percent_label,
    public_repair,
    public_verification,
)

SESSION_FILE = "active_backup_session.json"
HISTORY_FILE = "backup_session_history.jsonl"

# idevicebackup2 prints many tiny domain segments (often ~8MB) that hit 99–100%.
# Those must never drive overall backup % (hung-at-99 bug). Only "meaningful"
# segment totals count toward session_best / console overall evidence.
MIN_MEANINGFUL_SEGMENT_BYTES = 100 * 1024 * 1024  # 100 MB
# How much of the log to scan for session-wide best (live phase still uses active segment).
_PROGRESS_LOG_SCAN_BYTES = 12 * 1024 * 1024
# Disk-based overall must leave headroom until Backup Successful (never pin ~99%).
_DISK_PROGRESS_CAP = 92.0


def _session_path() -> Path:
    return ensure_internal() / SESSION_FILE


def _history_path() -> Path:
    return ensure_internal() / HISTORY_FILE


def _safe_name(s: str, *, max_len: int = 48) -> str:
    s = (s or "Device").strip()
    s = re.sub(r"[^\w\s.\-]+", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-._")
    return (s or "Device")[:max_len]


def next_backup_number(device_id: str) -> int:
    """Monotonic backup sequence per device (local)."""
    p = ensure_internal() / "backup_counters.json"
    data: dict[str, Any] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {}
    n = int(data.get(device_id) or 0) + 1
    data[device_id] = n
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return n


def _progress_store_path() -> Path:
    return ensure_internal() / "backup_high_water.json"


def load_device_high_water(device_id: str) -> float:
    """Durable per-device high-water % — survives lock, relaunch, log rotate."""
    p = _progress_store_path()
    if not p.exists():
        return 0.0
    try:
        data = json.loads(p.read_text())
        rec = data.get(device_id) or data.get("default") or {}
        return float(rec.get("percent") or 0)
    except Exception:
        return 0.0


def save_device_high_water(
    device_id: str,
    percent: float,
    *,
    label: str = "",
    completed: bool = False,
) -> None:
    """Persist high-water. Never store 100% unless completed=True (Backup Successful)."""
    p = _progress_store_path()
    data: dict[str, Any] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {}
    prev_rec = data.get(device_id) or {}
    prev = float(prev_rec.get("percent") or 0)
    prev_completed = bool(prev_rec.get("completed_at"))
    # Cap mid-run progress — false 100% from tiny segments / MB==MB poisons UI
    raw = float(percent or 0)
    if completed:
        pct = 100.0
    else:
        if raw >= 100.0:
            raw = 99.9
        # Drop poison durable 100 from incomplete runs
        if prev >= 100.0:
            prev = min(99.9, raw) if raw > 0 else 0.0
        # Recalibrate hung-at-95–99 poison (segment-local bars / disk pin) when
        # new honest evidence is lower and we never truly completed (deepcheck C3).
        if prev >= 95.0 and not prev_completed and 0.0 < raw < prev - 0.5:
            prev = raw
        pct = max(prev, raw)
        # Durable mid-run never stores above disk progress cap
        pct = min(_DISK_PROGRESS_CAP, pct)
    data[device_id] = {
        "percent": pct,
        "label": label,
        "updated_at": time.time(),
    }
    if completed:
        data[device_id]["completed_at"] = time.time()
    ensure_internal()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def clear_device_high_water(device_id: str) -> None:
    """Remove durable high-water for a device.

    Used on clean_dest so a new transfer does not inherit a false floor
    (especially a poison 100%). Real completion uses
    save_device_high_water(..., completed=True) — never this function.
    """
    if not device_id:
        return
    p = _progress_store_path()
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text())
        if device_id in data:
            del data[device_id]
            ensure_internal()
            p.write_text(json.dumps(data, indent=2))
            try:
                p.chmod(0o600)
            except OSError:
                pass
    except Exception:
        pass


def format_backup_label(
    *,
    device_name: str,
    data_kind: str,
    backup_number: int,
    when: datetime | None = None,
) -> str:
    """e.g. ROB-IPHONE-2-FullSystem-2026-07-19-Backup3-Cumulous"""
    when = when or datetime.now()
    return (
        f"{_safe_name(device_name)}-"
        f"{_safe_name(data_kind, max_len=32)}-"
        f"{when.strftime('%Y-%m-%d')}-"
        f"Backup{backup_number}-Cumulous"
    )


def load_session() -> dict[str, Any] | None:
    p = _session_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        # Recover truncated / multi-JSON session files
        try:
            text = p.read_text(errors="replace").strip()
            # Prefer last complete object
            if text.count("{") > 1:
                idx = text.rfind("\n{")
                if idx >= 0:
                    return json.loads(text[idx + 1 :])
            # First balanced attempt
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
        except Exception:
            return None
        return None


def save_session(session: dict[str, Any]) -> None:
    ensure_internal()
    session["updated_at"] = time.time()
    p = _session_path()
    # Atomic write so load_session never sees partial multi-docs
    tmp = p.parent / f"active_backup_session.{os.getpid()}.{int(time.time() * 1000)}.tmp"
    try:
        tmp.write_text(json.dumps(session, indent=2))
        os.replace(str(tmp), str(p))
    except Exception:
        try:
            p.write_text(json.dumps(session, indent=2))
        except Exception:
            pass
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    try:
        p.chmod(0o600)
    except OSError:
        pass


def clear_session() -> None:
    p = _session_path()
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


def append_history(event: dict[str, Any]) -> None:
    ensure_internal()
    with _history_path().open("a") as f:
        f.write(json.dumps({**event, "ts": time.time()}) + "\n")


def _ping_ms(host: str, port: int = 8765, timeout: float = 0.8) -> float | None:
    """RTT sample for live transport ranking (lower is better → higher score)."""
    import socket

    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return (time.time() - t0) * 1000.0
    except Exception:
        return None


def probe_transport() -> dict[str, Any]:
    """Rank available transports live (USB / Wi‑Fi usbmux / cellular mesh)."""
    usb = False
    usb_udid = ""
    try:
        cp = subprocess.run(
            ["idevice_id", "-l"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        lines = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
        if lines:
            usb = True
            usb_udid = lines[0]
    except Exception:
        pass

    wifi = False
    wifi_udid = ""
    try:
        cp = subprocess.run(
            ["idevice_id", "-n"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        lines = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
        if lines:
            wifi = True
            wifi_udid = lines[0]
    except Exception:
        pass

    # LAN vs Tailscale (cellular path when phone is on cell + Tailscale)
    lan_ms = _ping_ms("127.0.0.1")  # local bridge always
    ts_ip = None
    try:
        from cumulous.network_backup import tailscale_ip

        ts_ip = tailscale_ip()
    except Exception:
        ts_ip = None
    ts_ms = _ping_ms(ts_ip) if ts_ip else None

    # Scores: higher = better for *system* backup path
    # USB wins when present; else wireless usbmux; else progressive API over fastest IP path
    wifi_score = 0.0
    if wifi:
        wifi_score = 40.0
        if lan_ms is not None:
            wifi_score += max(0.0, 25.0 - min(lan_ms, 200.0) / 8.0)
    cell_score = 0.0
    if ts_ip:
        cell_score = 12.0
        if ts_ms is not None:
            cell_score += max(0.0, 20.0 - min(ts_ms, 400.0) / 15.0)
        # If no USB/wifi usbmux, cellular mesh is still valid for progressive continue
        if not usb and not wifi:
            cell_score = max(cell_score, 18.0)

    scores = {
        "usb": 100.0 if usb else 0.0,
        "wifi": wifi_score,
        "cellular": cell_score,
        "progressive_api": 20.0 if (usb or wifi or ts_ip) else 5.0,
    }
    # Preferred for full system dump: usb > wifi usbmux > cellular (progressive)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best = ranked[0][0] if ranked and ranked[0][1] > 0 else "none"
    return {
        "usb": usb,
        "usb_udid": usb_udid,
        "wifi_usbmux": wifi,
        "wifi_udid": wifi_udid,
        "tailscale_ip": ts_ip,
        "lan_rtt_ms": lan_ms,
        "cellular_rtt_ms": ts_ms,
        "scores": scores,
        "preferred": best,
        "unplug_policy": "never_cancel — hand off to best of wifi/cellular automatically",
        "lock_note": (
            "Screen-lock during backup is suppressed in Cumulous app (idle timer off). "
            "If Apple asks for a one-time computer passcode, enter it once; auto-resume follows."
        ),
    }


def repair_incremental_backup(dest: Path, udid: str) -> dict[str, Any]:
    """Repair interrupted idevicebackup2 tree so resume works on modern iOS.

    Error 205 (MBErrorDomain/11) "Invalid snapshot state name" happens when
    Status.plist + incomplete Snapshot/ disagree. Device rejects both "new" and
    "Finished" while a partial Snapshot is present. Fix: quarantine Snapshot,
    remove Status.plist so the next backup starts clean (Info.plist kept).
    Never delete Snapshot.partial.* (CEO forensic / recovery).
    """
    import plistlib

    device_dir = dest / udid
    result: dict[str, Any] = {"ok": True, "actions": [], "device_dir": str(device_dir)}
    if not dest.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        result["actions"].append("created_dest")
    if not device_dir.is_dir():
        result["actions"].append("no_device_dir_yet")
        return result

    status_path = device_dir / "Status.plist"
    info_path = device_dir / "Info.plist"
    snap_dir = device_dir / "Snapshot"
    has_manifest = (device_dir / "Manifest.db").is_file() or (
        device_dir / "Manifest.plist"
    ).is_file()

    # Never disturb a live idevicebackup2 Snapshot mid-transfer
    live_backup = False
    try:
        cp = subprocess.run(
            ["pgrep", "-x", "idevicebackup2"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        live_backup = bool((cp.stdout or "").strip())
    except Exception:
        live_backup = False
    if live_backup:
        result["actions"].append("skip_repair_live_idevicebackup2")
        result["file_count"] = 0
        return result

    # Quarantine ONLY proven-toxic incomplete Snapshot (Error 205 states), not active transfers
    st0: dict[str, Any] = {}
    if status_path.is_file():
        try:
            with status_path.open("rb") as f:
                st0 = plistlib.load(f) or {}
        except Exception:
            st0 = {}
    snap_state = str(st0.get("SnapshotState") or "").lower()
    toxic_state = snap_state in ("new", "uploading")
    # Fresh Snapshot without toxic Status = likely live transfer — leave alone
    snap_fresh = False
    if snap_dir.is_dir():
        try:
            snap_fresh = (time.time() - snap_dir.stat().st_mtime) < 180
        except Exception:
            snap_fresh = False

    # Quarantine toxic incomplete Snapshot (Error 205). Live process already returned above.
    # Non-toxic + fresh Snapshot is left intact (active or just-paused healthy transfer).
    if snap_dir.is_dir() and not has_manifest and toxic_state:
        try:
            has_files = any(snap_dir.iterdir())
        except Exception:
            has_files = False
        if has_files:
            park = device_dir / f"Snapshot.partial.{int(time.time())}"
            try:
                snap_dir.rename(park)
                result["actions"].append(f"quarantined_toxic_snapshot->{park.name}")
            except Exception as e:
                result["actions"].append(f"snapshot_quarantine_fail:{e!s}"[:100])
    elif snap_dir.is_dir() and snap_fresh and not has_manifest and not toxic_state:
        result["actions"].append("fresh_healthy_snapshot_left_intact")

    # Remove Status only when toxic state + no Manifest (not during healthy empty Status)
    if not has_manifest and status_path.is_file() and toxic_state:
        try:
            bak = device_dir / f"Status.plist.bak.{int(time.time())}"
            status_path.replace(bak)
            result["actions"].append(f"removed_poison_status->{bak.name}")
            result["status"] = None
        except Exception as e:
            result["actions"].append(f"status_remove_fail:{e!s}"[:80])
    elif has_manifest and status_path.is_file():
        try:
            with status_path.open("rb") as f:
                st = plistlib.load(f) or {}
            if not st.get("SnapshotState"):
                st["SnapshotState"] = "Finished"
                st["Date"] = datetime.now(timezone.utc)
                with status_path.open("wb") as f:
                    plistlib.dump(st, f)
                result["actions"].append("filled_missing_snapshotstate_Finished")
            result["status"] = {
                k: st.get(k) for k in ("BackupState", "SnapshotState", "IsFullBackup", "Version")
            }
        except Exception as e:
            result["actions"].append(f"status_read_fail:{e!s}"[:80])
    elif not status_path.is_file():
        result["actions"].append("no_status_plist_clean_start")
    else:
        result["actions"].append("status_left_intact")
        result["status"] = {
            k: st0.get(k) for k in ("BackupState", "SnapshotState", "IsFullBackup", "Version")
        }

    if not info_path.is_file():
        result["actions"].append("missing_info_plist_will_be_rewritten_by_idevicebackup2")
    if not has_manifest:
        result["actions"].append("no_manifest_yet_incomplete_or_first_run")
    try:
        result["file_count"] = sum(1 for _ in device_dir.rglob("*") if _.is_file())
    except Exception:
        result["file_count"] = 0
    return result


_SIZE_RE = re.compile(
    r"^\s*([\d]+(?:\.\d+)?)\s*(BYTES?|B|KB|MB|GB|TB|KIB|MIB|GIB|TIB)?\s*$",
    re.IGNORECASE,
)
_PROGRESS_RE = re.compile(r"(\d{1,3})%\s*\(([^/]+)/([^)]+)\)")


def _parse_size_to_bytes(label: str | None) -> float | None:
    """Parse idevicebackup2 size labels like '382.4 MB' or '2.6 GB' → bytes."""
    if not label:
        return None
    m = _SIZE_RE.match(str(label).strip().replace(",", ""))
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "B").upper()
    if unit in ("BYTE", "BYTES"):
        unit = "B"
    mult = {
        "B": 1.0,
        "KB": 1000.0,
        "KIB": 1024.0,
        "MB": 1000.0**2,
        "MIB": 1024.0**2,
        "GB": 1000.0**3,
        "GIB": 1024.0**3,
        "TB": 1000.0**4,
        "TIB": 1024.0**4,
    }.get(unit, 1.0)
    return n * mult


def _log_active_segment(text: str) -> str:
    """Only the latest launch segment — ignore stale 'Waiting for passcode' from old runs."""
    markers = (
        "\n--- launch ",
        "\n--- relaunch ",
        "--- launch ",
        "--- relaunch ",
    )
    idx = -1
    for m in markers:
        pos = text.rfind(m)
        if pos > idx:
            idx = pos
    if idx >= 0:
        return text[idx:]
    return text[-8192:] if len(text) > 8192 else text


def _extract_progress_matches(norm: str) -> list[tuple[float, str, str]]:
    """Return (percent, done_label, total_label) for every progress bar hit."""
    out: list[tuple[float, str, str]] = []
    for pct_s, done_s, tot_s in _PROGRESS_RE.findall(norm):
        try:
            pct = float(pct_s)
        except ValueError:
            continue
        if 0.0 <= pct <= 100.0:
            out.append((pct, done_s.strip(), tot_s.strip()))
    return out


def _parse_progress_from_log(log_path: Path) -> dict[str, Any]:
    """Parse idevicebackup2 progress.

    - *Live* phase/wait from the current launch segment only.
    - *Best percent* and byte labels from the full log (session truth).
    """
    out: dict[str, Any] = {
        "percent": None,  # live segment (or best if live missing)
        "live_percent": None,
        "session_best_percent": None,
        "bytes_done": None,
        "bytes_total": None,
        "bytes_done_label": None,
        "bytes_total_label": None,
        "phase": "unknown",
        "raw_tail": "",
        "waiting_passcode": False,
        "error": None,
        "receiving": False,
        "aborted": False,
        "protocol_ok": False,
        "has_console_progress": False,
        "live_segment_tiny": False,
        "largest_meaningful_total": None,
    }
    if not log_path.is_file():
        return out
    try:
        data = log_path.read_bytes()
        # Keep a large window so multi-GB segment highs aren't lost to a tail of 8MB domains
        if len(data) > _PROGRESS_LOG_SCAN_BYTES:
            data = data[-_PROGRESS_LOG_SCAN_BYTES:]
        full = data.decode("utf-8", errors="replace")
        full_norm = full.replace("\r", "\n")
        segment = _log_active_segment(full)
        seg_norm = segment.replace("\r", "\n")
        out["raw_tail"] = seg_norm[-500:]

        # Session-wide best — only *meaningful* mid-progress segments (not ~8MB domain noise).
        # A finished segment at 100% of its own total is NOT overall progress 99% (hung-at-99).
        all_hits = _extract_progress_matches(full_norm)
        if all_hits:
            out["has_console_progress"] = True

            def _tot(h: tuple[float, str, str]) -> float:
                return _parse_size_to_bytes(h[2]) or 0.0

            def _meaningful_mid(h: tuple[float, str, str]) -> bool:
                tot = _tot(h)
                pct = float(h[0])
                # Exclude 99–100% segment tails — they are domain-complete noise for overall %
                return tot >= MIN_MEANINGFUL_SEGMENT_BYTES and 0.0 <= pct < 99.0

            meaningful_mids = [h for h in all_hits if _meaningful_mid(h)]
            meaningful_any = [
                h
                for h in all_hits
                if _tot(h) >= MIN_MEANINGFUL_SEGMENT_BYTES
            ]
            if meaningful_any:
                out["largest_meaningful_total"] = max(_tot(h) for h in meaningful_any)

            if meaningful_mids:
                # Prefer most bytes actually received mid-segment (not 0% of a large total
                # header, and not a near-empty 4.2GB line that outranks real progress).
                def _mid_score(h: tuple[float, str, str]) -> tuple[float, float, float]:
                    done = _parse_size_to_bytes(h[1]) or 0.0
                    pct = float(h[0])
                    return (done, pct, _tot(h))

                best = max(meaningful_mids, key=_mid_score)
                out["session_best_percent"] = float(best[0])
                out["bytes_done_label"] = best[1]
                out["bytes_total_label"] = best[2]
                out["bytes_done"] = _parse_size_to_bytes(best[1])
                out["bytes_total"] = _parse_size_to_bytes(best[2])
            elif meaningful_any:
                # Only completed large segments — labels only, no false 99% best
                best = max(meaningful_any, key=_tot)
                out["bytes_done_label"] = best[1]
                out["bytes_total_label"] = best[2]
                out["bytes_done"] = _parse_size_to_bytes(best[1])
                out["bytes_total"] = _parse_size_to_bytes(best[2])

        # Live segment
        wait_markers = (
            "*** Waiting for passcode",
            "Waiting for passcode to be entered on the device",
            "ErrorCode 208",
            "MBErrorDomain/208",
            "Device locked",
        )
        live_hits = _extract_progress_matches(seg_norm)
        receiving = "Receiving files" in segment or "Receiving" in segment
        protocol_ok = "Negotiated Protocol Version" in segment or "Starting backup" in segment
        out["protocol_ok"] = protocol_ok
        out["receiving"] = receiving

        if live_hits:
            live = live_hits[-1]
            live_tot = _parse_size_to_bytes(live[2]) or 0.0
            live_done = _parse_size_to_bytes(live[1]) or 0.0
            out["live_percent"] = float(live[0])
            out["bytes_done_label"] = live[1]
            out["bytes_total_label"] = live[2]
            out["live_bytes_done"] = live_done
            out["live_bytes_total"] = live_tot
            out["live_segment_tiny"] = live_tot < MIN_MEANINGFUL_SEGMENT_BYTES
            # Only promote live console to overall evidence when segment is meaningful
            if not out["live_segment_tiny"]:
                out["percent"] = float(live[0])
                out["bytes_done"] = live_done
                out["bytes_total"] = live_tot
            out["phase"] = "receiving"
            out["waiting_passcode"] = False
            out["has_console_progress"] = True
            out["receiving"] = True
        elif out["session_best_percent"] is not None:
            # No live bar in this segment — keep best known *meaningful* console % as soft evidence
            out["percent"] = out["session_best_percent"]

        wait_pos = max((seg_norm.rfind(m) for m in wait_markers), default=-1)
        last_pct_pos = seg_norm.rfind("% (") if "% (" in seg_norm else -1
        if wait_pos >= 0 and wait_pos > last_pct_pos and out["live_percent"] is None:
            out["waiting_passcode"] = True
            out["phase"] = "waiting_passcode"
        elif receiving and not out["waiting_passcode"]:
            out["phase"] = "receiving"

        if "Backup Successful" in segment or "Backup successful" in segment:
            out["percent"] = 100.0
            out["live_percent"] = 100.0
            out["session_best_percent"] = max(float(out["session_best_percent"] or 0), 100.0)
            out["phase"] = "complete"
            out["waiting_passcode"] = False

        abort_pos = max(
            seg_norm.rfind("Backup Aborted"),
            seg_norm.rfind("Backup Failed"),
            seg_norm.rfind("ERROR:"),
            seg_norm.rfind("Exiting..."),
        )
        if abort_pos >= 0 and abort_pos > last_pct_pos and out["phase"] != "complete":
            out["aborted"] = True
            for line in reversed(seg_norm.splitlines()):
                if "ERROR" in line or "Aborted" in line or "ErrorCode" in line or "Backup Failed" in line:
                    out["error"] = line.strip()[:200]
                    break
            err = (out.get("error") or "") + seg_norm[max(0, abort_pos - 200) : abort_pos + 80]
            # 208 = passcode lock; 205 = snapshot/status repair (NOT passcode)
            if "205" in err or "Invalid snapshot state" in err:
                out["phase"] = "error"
                out["waiting_passcode"] = False
                out["error"] = (out.get("error") or "Error 205")[:200]
            elif "208" in err or ("Device locked" in err and "205" not in err):
                out["waiting_passcode"] = True
                out["phase"] = "waiting_passcode"
            elif "Waiting for passcode" in err and "205" not in err and "Aborted" not in err:
                out["waiting_passcode"] = True
                out["phase"] = "waiting_passcode"
            else:
                out["phase"] = "error"
                out["waiting_passcode"] = False

        if "Sending '" in segment and out["phase"] == "unknown":
            out["phase"] = "sending"
        if "Incremental backup mode" in segment and out["phase"] == "unknown":
            out["phase"] = "starting"
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


def _independent_estimated_total(
    *,
    session: dict[str, Any],
    disk_bytes: float,
    console_total: float | None,
    console_done: float | None,
    largest_meaningful_total: float | None = None,
) -> float:
    """Estimate final size from non-self-referential signals only.

    Never uses disk/0.99 — that pinned overall progress at ~99% (hung-at-99 bug).
    Tiny console totals are ignored. When disk has already grown past known
    targets, keep ≥8% headroom so disk % cannot read as ~99% mid-run.
    """
    candidates: list[float] = []
    est = float(session.get("estimated_total_bytes") or 0)
    base = float(session.get("baseline_bytes") or 0)
    # Ignore estimates that are only a hair above disk (self-inflated)
    if est > 0 and (disk_bytes <= 0 or est > disk_bytes * 1.08):
        candidates.append(est)

    # Only meaningful console totals (skip ~8MB domain segments)
    if (
        console_total
        and float(console_total) >= MIN_MEANINGFUL_SEGMENT_BYTES
    ):
        candidates.append(float(console_total))
        remaining = max(0.0, float(console_total) - float(console_done or 0))
        candidates.append(max(disk_bytes, base) + remaining)
        candidates.append(base + float(console_total))
    if largest_meaningful_total and float(largest_meaningful_total) >= MIN_MEANINGFUL_SEGMENT_BYTES:
        candidates.append(float(largest_meaningful_total))

    # Device used-capacity hint when available (session may stash it)
    dev_used = float(session.get("device_data_used_bytes") or 0)
    if dev_used > 0:
        candidates.append(dev_used * 1.5)
        candidates.append(dev_used + 8_000_000_000)

    if candidates:
        refined = max(candidates)
    elif disk_bytes > 0:
        # Unknown final size: keep headroom; GB-scale trees get a 12GB floor
        refined = max(
            disk_bytes / (_DISK_PROGRESS_CAP / 100.0),
            disk_bytes + (3_000_000_000 if disk_bytes >= 1_000_000_000 else disk_bytes * 0.25),
        )
        if disk_bytes >= 1_000_000_000:
            refined = max(refined, 12_000_000_000.0)
    else:
        refined = 12_000_000_000.0

    # Leave headroom above current disk so incomplete runs cap near
    # _DISK_PROGRESS_CAP, never 99% from disk≈estimate. Skip the +3GB pad for
    # small test trees / partials under 1GB so unit estimates stay honest.
    if disk_bytes > 0:
        refined = max(refined, disk_bytes / (_DISK_PROGRESS_CAP / 100.0))
        if disk_bytes >= 1_000_000_000:
            refined = max(refined, disk_bytes + 3_000_000_000)
    return max(refined, 1.0)


def _refine_estimated_total(
    *,
    session: dict[str, Any],
    disk_bytes: float,
    console_total: float | None,
    console_done: float | None,
    largest_meaningful_total: float | None = None,
) -> float:
    """Best-effort final size for overall % (never below current disk)."""
    refined = _independent_estimated_total(
        session=session,
        disk_bytes=disk_bytes,
        console_total=console_total,
        console_done=console_done,
        largest_meaningful_total=largest_meaningful_total,
    )
    return max(refined, float(disk_bytes or 0), 1.0)


def _compute_accurate_percent(
    *,
    parsed: dict[str, Any],
    disk_bytes: float,
    baseline: float,
    estimated_total: float,
    session_high: float,
    device_data_used: float = 0.0,
) -> tuple[float, dict[str, Any]]:
    """Multi-signal percent. Returns (percent, debug meta). Never trusts orphan high-water alone."""
    meta: dict[str, Any] = {"signals": {}}
    signals: list[tuple[str, float]] = []

    live = parsed.get("live_percent")
    live_tiny = bool(parsed.get("live_segment_tiny"))
    live_tot = parsed.get("live_bytes_total")
    if live_tot is None:
        live_tot = parsed.get("bytes_total")
    done_b = parsed.get("bytes_done")
    tot_b = parsed.get("bytes_total")
    largest = parsed.get("largest_meaningful_total")

    # Console domain bars are segment-local — never treat raw 0–100% as overall.
    # Scale meaningful console progress by segment size / estimated final size.
    if live is not None:
        meta["signals"]["console_live_raw"] = float(live)
        if live_tiny:
            meta["signals"]["console_live_ignored_tiny"] = float(live)

    best = parsed.get("session_best_percent")
    if best is not None:
        meta["signals"]["console_session_best_raw"] = float(best)

    sess_for_est = {
        "estimated_total_bytes": estimated_total,
        "baseline_bytes": baseline,
        "device_data_used_bytes": device_data_used,
    }
    ind_est = _independent_estimated_total(
        session=sess_for_est,
        disk_bytes=disk_bytes,
        console_total=float(tot_b)
        if isinstance(tot_b, (int, float)) and float(tot_b) >= MIN_MEANINGFUL_SEGMENT_BYTES
        else None,
        console_done=float(done_b) if isinstance(done_b, (int, float)) else None,
        largest_meaningful_total=float(largest) if largest else None,
    )
    est = _refine_estimated_total(
        session=sess_for_est,
        disk_bytes=disk_bytes,
        console_total=float(tot_b)
        if isinstance(tot_b, (int, float)) and float(tot_b) >= MIN_MEANINGFUL_SEGMENT_BYTES
        else None,
        console_done=float(done_b) if isinstance(done_b, (int, float)) else None,
        largest_meaningful_total=float(largest) if largest else None,
    )
    meta["estimated_total_bytes"] = est
    meta["independent_estimated_total"] = ind_est

    # Disk overall — hard-capped so incomplete backups never hang at 99%
    if est > 0 and disk_bytes > 0:
        disk_abs = min(_DISK_PROGRESS_CAP, max(0.0, 100.0 * disk_bytes / est))
        signals.append(("disk_absolute", disk_abs))
        meta["signals"]["disk_absolute"] = disk_abs

    if est > baseline >= 0 and disk_bytes >= baseline:
        gained = disk_bytes - baseline
        target = max(est - baseline, 1.0)
        disk_gain = min(_DISK_PROGRESS_CAP, max(0.0, 100.0 * gained / target))
        signals.append(("disk_gain", disk_gain))
        meta["signals"]["disk_gain"] = disk_gain

    # Scale large console segments into overall space: (done/est)*100
    if (
        isinstance(done_b, (int, float))
        and float(done_b) > 0
        and est > 0
        and isinstance(tot_b, (int, float))
        and float(tot_b) >= MIN_MEANINGFUL_SEGMENT_BYTES
    ):
        scaled = min(_DISK_PROGRESS_CAP, max(0.0, 100.0 * float(done_b) / est))
        signals.append(("console_scaled", scaled))
        meta["signals"]["console_scaled"] = scaled

    if (
        live is not None
        and not live_tiny
        and live_tot is not None
        and float(live_tot) >= MIN_MEANINGFUL_SEGMENT_BYTES
        and est > 0
    ):
        live_done = float(live_tot) * (float(live) / 100.0)
        scaled_live = min(_DISK_PROGRESS_CAP, max(0.0, 100.0 * live_done / est))
        signals.append(("console_live_scaled", scaled_live))
        meta["signals"]["console_live_scaled"] = scaled_live

    if parsed.get("phase") == "complete":
        meta["chosen"] = "complete"
        return 100.0, meta

    # Incomplete runs: hard-cap so UI cannot hang at 99/100
    def _cap(p: float) -> float:
        return min(_DISK_PROGRESS_CAP, max(0.0, float(p)))

    sh = float(session_high or 0)
    if sh >= 100.0:
        meta["dropped_false_100_high_water"] = sh
        sh = 0.0

    evidence = max((v for _, v in signals), default=0.0)
    meta["evidence_max"] = evidence

    # Soft-drop poison high-water that was inflated by segment-local 99% bars
    if sh > _DISK_PROGRESS_CAP:
        meta["soft_dropped_above_cap"] = sh
        sh = _DISK_PROGRESS_CAP
    if sh >= 95.0 and evidence < sh - 1.0:
        meta["soft_dropped_hung_high"] = sh
        sh = max(evidence, min(sh, 88.0))

    if not signals:
        meta["chosen"] = "session_high_only"
        return _cap(sh), meta

    # Overall = max(honest evidence, sticky floor) — never raw segment %
    chosen = max(evidence, sh)
    if parsed.get("receiving") or parsed.get("phase") == "receiving":
        meta["chosen"] = "disk_and_scaled_console"
    elif parsed.get("waiting_passcode") or parsed.get("aborted") or parsed.get("phase") == "error":
        meta["chosen"] = "hold_prior_wait"
    else:
        meta["chosen"] = "max_evidence_and_high_water"
    return _cap(chosen), meta


def device_currently_locked(udid: str = "") -> dict[str, Any]:
    """Live lock probe — PasswordProtected means 'has passcode', NOT 'is locked now'."""
    result: dict[str, Any] = {
        "locked": None,  # True/False/None
        "has_passcode_enabled": None,
        "reachable": False,
        "udid": udid,
        "method": None,
    }
    if not udid:
        try:
            cp = subprocess.run(
                ["idevice_id", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            lines = [ln.strip() for ln in (cp.stdout or "").splitlines() if ln.strip()]
            udid = lines[0] if lines else ""
            result["udid"] = udid
        except Exception:
            return result
    if not udid:
        return result

    # has_passcode_enabled (often true even while unlocked — DO NOT use as locked)
    try:
        cp = subprocess.run(
            ["ideviceinfo", "-u", udid, "-k", "PasswordProtected"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        val = (cp.stdout or "").strip().lower()
        if val in ("true", "false"):
            result["has_passcode_enabled"] = val == "true"
            result["reachable"] = True
    except Exception:
        pass

    # Reachability: can we read ProductVersion?
    try:
        cp = subprocess.run(
            ["ideviceinfo", "-u", udid, "-k", "ProductVersion"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        if (cp.stdout or "").strip():
            result["reachable"] = True
        elif cp.returncode != 0:
            # Unreachable might mean locked USB path or unplugged
            err = (cp.stderr or "") + (cp.stdout or "")
            if "locked" in err.lower() or "password" in err.lower():
                result["locked"] = True
                result["method"] = "ideviceinfo_error"
    except Exception:
        pass

    # If we cannot decide from lockdown, leave locked=None and let backup process decide
    if result["locked"] is None and result["reachable"]:
        # Unlocked enough for lockdown queries — treat as unlocked for UI
        # (full backup may still prompt once; we auto-resume)
        result["locked"] = False
        result["method"] = "lockdown_reachable"
    return result


def _dir_stats(path: Path) -> dict[str, Any]:
    total = 0
    count = 0
    if not path.is_dir():
        return {"bytes": 0, "files": 0}
    for root, _dirs, files in os.walk(path):
        for name in files:
            if name.startswith("."):
                continue
            fp = Path(root) / name
            try:
                total += fp.stat().st_size
                count += 1
            except OSError:
                continue
    return {"bytes": total, "files": count}


def _process_alive(pid: Any) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def session_public_view(session: dict[str, Any] | None = None) -> dict[str, Any]:
    """CEO-safe progress payload for Mac mini-window + iOS banner."""
    session = session or load_session()
    if not session:
        return {
            "active": False,
            "percent": 0,
            "percent_int": 0,
            "high_water_percent": 0,
            "status_line": "No backup running",
            "message": "No backup running",
            "waiting_passcode": False,
            "power": _power_payload(),
        }

    log = Path(session.get("log_path") or "")
    dest = Path(session.get("dest_path") or "")
    # Heal broken/placeholder log paths (historical /tmp/no-such-bak.log) while process logs there
    if (not log.is_file() or log.name in ("no-such-bak.log",)) and dest:
        alt = dest.parent / f"{dest.name}.log"
        if alt.is_file():
            log = alt
            session["log_path"] = str(alt)
        elif Path("/tmp/no-such-bak.log").is_file() and log.name == "no-such-bak.log":
            log = Path("/tmp/no-such-bak.log")
    parsed = _parse_progress_from_log(log) if log.is_file() else {}
    stats = _dir_stats(dest) if dest else {"bytes": 0, "files": 0}
    alive = _process_alive(session.get("pid"))
    # If session tracked a pid that exited, re-bind to the single live process
    # (do not invent aliveness when pid was never set — keeps unit tests honest).
    if not alive and session.get("pid"):
        try:
            cp = subprocess.run(
                ["pgrep", "-x", "idevicebackup2"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            pids = [x for x in (cp.stdout or "").split() if x]
            if len(pids) == 1:
                alive = True
                session["pid"] = int(pids[0])
        except Exception:
            pass
    lock = device_currently_locked(str(session.get("udid") or ""))

    baseline = float(session.get("baseline_bytes") or 0)
    est_total = float(session.get("estimated_total_bytes") or 0)
    cur = float(stats.get("bytes") or 0)
    # Baseline cannot exceed current disk (repair/rewrite); re-anchor
    if baseline > cur + 1024 and cur > 0:
        baseline = cur
        session["baseline_bytes"] = baseline
    prev_disk = float(session.get("disk_bytes") or baseline or 0)
    growing = cur > prev_disk + 1024  # >1KB growth since last view
    device_id = str(session.get("device_id") or session.get("udid") or "")
    udid = str(session.get("udid") or "")
    # Durable floor: never return to 0% after lock / relaunch / log rotate
    durable_high = 0.0
    if device_id:
        durable_high = max(durable_high, load_device_high_water(device_id))
    if udid and udid != device_id:
        durable_high = max(durable_high, load_device_high_water(udid))
    session_high = max(
        float(session.get("high_water_percent") or 0),
        float(session.get("last_percent") or 0),
        durable_high,
    )

    # Device used-capacity hint for estimate (best-effort, never blocks)
    device_data_used = float(session.get("device_data_used_bytes") or 0)
    if device_data_used <= 0 and udid:
        try:
            from cumulous.device_capacity import capacity_report

            device_data_used = float((capacity_report(udid=udid) or {}).get("data_used_bytes") or 0)
            if device_data_used > 0:
                session["device_data_used_bytes"] = device_data_used
        except Exception:
            device_data_used = 0.0

    # --- Accurate multi-signal percent ---
    percent, pct_meta = _compute_accurate_percent(
        parsed=parsed,
        disk_bytes=cur,
        baseline=baseline,
        estimated_total=est_total,
        session_high=session_high,
        device_data_used=device_data_used,
    )
    # Keep estimate honest for next poll
    if pct_meta.get("estimated_total_bytes"):
        session["estimated_total_bytes"] = float(pct_meta["estimated_total_bytes"])
    last = float(percent or 0)

    # --- Status state machine (not sticky waiting_passcode) ---
    phase = parsed.get("phase") or "unknown"
    waiting = bool(parsed.get("waiting_passcode"))

    # Live *transfer* always clears wait (device unlocked enough to send files)
    has_live_transfer = bool(
        parsed.get("receiving")
        or (parsed.get("live_percent") is not None and float(parsed["live_percent"]) > 0)
        or growing
    )
    if has_live_transfer:
        waiting = False
        if phase in ("waiting_passcode", "unknown", "error", "needs_resume"):
            phase = "receiving"

    # NOTE: do NOT clear wait solely because lockdown is reachable.
    # PasswordProtected / lockdown can succeed while mobilebackup2 still
    # waits for a one-time computer passcode (Error 208). Only transfer clears wait.

    # Live transport — critical for honest "paused vs running" UI
    try:
        live_transport = probe_transport()
    except Exception:
        live_transport = {}
    has_usb = bool(live_transport.get("usb"))
    has_wifi = bool(live_transport.get("wifi_usbmux"))
    has_path = has_usb or has_wifi

    if parsed.get("phase") == "complete":
        status = "complete"
        phase = "complete"
        percent = 100.0
        waiting = False
    elif waiting and alive and not has_live_transfer:
        # Only "waiting passcode" while process is actually alive
        status = "waiting_passcode"
        phase = "waiting_passcode"
    elif alive or growing or has_live_transfer:
        status = "running"
        if phase in ("waiting_passcode", "unknown", "needs_resume", "error"):
            phase = "receiving" if has_live_transfer else "starting"
    elif parsed.get("aborted") or parsed.get("phase") == "error":
        status = "needs_resume"
        phase = "needs_resume"
        waiting = False
    else:
        # Process dead — resume-capable; never sticky-wait without live process
        waiting = False
        if session.get("status") in ("complete", "cancelled"):
            status = str(session.get("status"))
            phase = status
        else:
            status = "needs_resume"
            phase = "awaiting_usb" if not has_path else "needs_resume"

    # Prefer live preferred transport label when connected
    if has_usb:
        transport = "usb"
    elif has_wifi:
        transport = "wifi"
    else:
        transport = session.get("active_transport") or session.get("transport") or "none"
    session["active_transport"] = transport

    pct_held = int(round(float(percent or session_high or 0)))
    function_line = {
        "waiting_passcode": (
            "On the iPhone screen: enter your passcode if Apple asks "
            "(required once for backup, even when already unlocked) · leave awake"
        ),
        "receiving": f"Copying files · {str(transport).upper()}",
        "sending": f"Connecting · {str(transport).upper()}",
        "starting": f"Starting · {str(transport).upper()}",
        "complete": "Finished",
        "error": "Paused — will continue automatically",
        "running": f"Backing up · {str(transport).upper()}",
        "needs_resume": (
            f"Paused at {pct_held}% · plug USB to continue"
            if not has_path
            else f"Paused at {pct_held}% · reconnecting · enter passcode on phone if asked"
        ),
        "awaiting_usb": f"Paused at {pct_held}% · plug the iPhone into this Mac (USB)",
        "handoff": "Cable unplugged — continuing on Wi‑Fi",
        "awaiting_network": "Waiting for Wi‑Fi — backup continues when ready",
        "unknown": (
            f"Paused at {pct_held}% · plug USB to continue"
            if not has_path and not alive
            else f"Backing up · {str(transport).upper()}"
        ),
    }.get(str(phase), "Backing up")

    # Clear stale last_error when healthy
    if status == "running" and not parsed.get("aborted"):
        session["last_error"] = None
    elif parsed.get("error"):
        session["last_error"] = parsed.get("error")

    # High-water = verified percent (never 100 mid-run)
    high = float(percent or 0)
    if status == "complete":
        high = 100.0
        percent = 100.0
    else:
        if high >= 100.0:
            high = 99.9
        if percent >= 100.0:
            percent = 99.9
    session["last_percent"] = float(percent or 0)
    session["high_water_percent"] = high
    session["percent_meta"] = {
        "chosen": pct_meta.get("chosen"),
        "signals": pct_meta.get("signals"),
        "estimated_total_bytes": pct_meta.get("estimated_total_bytes"),
    }
    session["status"] = status
    session["phase"] = phase
    session["disk_bytes"] = cur
    session["disk_files"] = stats.get("files")
    session["waiting_passcode"] = waiting
    session["lock_probe"] = {
        "locked": lock.get("locked"),
        "has_passcode_enabled": lock.get("has_passcode_enabled"),
        "note": "PasswordProtected=true only means a passcode is SET, not that the screen is locked now.",
    }
    if parsed.get("bytes_done_label"):
        session["bytes_done_label"] = parsed["bytes_done_label"]
        session["bytes_total_label"] = parsed.get("bytes_total_label")
    elif not parsed.get("has_console_progress"):
        # Drop stale labels from older sessions when this log has no progress bar
        session.pop("bytes_done_label", None)
        session.pop("bytes_total_label", None)
    save_session(session)
    if device_id:
        save_device_high_water(
            device_id,
            high,
            label=str(session.get("label") or ""),
            completed=(status == "complete"),
        )
        if udid and udid != device_id:
            save_device_high_water(
                udid,
                high,
                label=str(session.get("label") or ""),
                completed=(status == "complete"),
            )
        # On complete, durable 100% is already stored via save_device_high_water(completed=True).
        # Do NOT clear_device_high_water here — that would delete the success floor.

    # Keep-awake must stay engaged for any non-terminal backup state
    if status not in ("complete", "cancelled", "idle"):
        try:
            from cumulous.device_power import begin_backup_wake_policy, load_power_state

            if not load_power_state().get("active"):
                begin_backup_wake_policy(
                    session_id=str(session.get("session_id") or ""),
                    device_name=str(session.get("device_name") or ""),
                )
        except Exception:
            pass

    # Never show 100 / hung-99 in the integer label unless truly complete.
    if status == "complete":
        pct_i = 100
    else:
        # Floor then min so 92.4 → 92, and never advertise 99 mid-run from noise
        pct_i = int(float(percent or 0))
        if pct_i >= 99:
            pct_i = min(pct_i, int(_DISK_PROGRESS_CAP))
        pct_i = max(0, min(98, pct_i))
    headline = progress_headline(pct_i, status=status)
    # "Active" = work in flight OR a paused session that will auto-resume.
    # UI distinguishes paused (no process) via status_line / process_alive.
    is_terminal = status in ("complete", "idle", "cancelled")
    is_paused_resume = status in ("needs_resume", "awaiting_usb", "awaiting_network", "handoff")
    is_live = bool(alive or growing or has_live_transfer or waiting)
    return {
        "active": (not is_terminal) and (is_live or is_paused_resume),
        "paused": is_paused_resume and not is_live,
        "status": status,
        "phase": phase,
        "percent": float(percent or 0),
        "percent_int": pct_i,
        "high_water_percent": high,
        "message": f"{headline}: {progress_percent_label(pct_i)}",
        "status_line": function_line,
        "device_name": session.get("device_name"),
        "device_id": session.get("device_id"),
        "label": session.get("label"),
        "transport": transport,
        "transports": session.get("transport_scores") or {},
        "dest_path": str(dest) if dest else "",
        "disk_bytes": cur,
        "disk_files": stats.get("files"),
        "bytes_done_label": session.get("bytes_done_label"),
        "bytes_total_label": session.get("bytes_total_label"),
        "waiting_passcode": waiting,
        "error": client_error(parsed.get("error") or session.get("last_error"), status=status),
        "started_at": session.get("started_at"),
        "updated_at": session.get("updated_at"),
        "keep_awake_policy": session.get("keep_awake_policy"),
        "verification": public_verification(session.get("verification")),
        "process_alive": alive,
        "disk_growing": growing,
        "lock_probe": {"locked": (session.get("lock_probe") or lock or {}).get("locked")},
        "incremental_repair": public_repair(session.get("incremental_repair")),
        "unplug_ends_backup": False,
        "auto_continue_on_unplug": True,
        "unplug_safe": True,
        "percent_source": (session.get("percent_meta") or {}).get("chosen"),
        "power": _power_payload(),
    }


def _power_payload() -> dict[str, Any]:
    try:
        from cumulous.device_power import power_policy_for_clients

        return power_policy_for_clients()
    except Exception:
        return {"keep_awake": False, "ios_disable_idle_timer": False}


_orch_lock = threading.Lock()
_orch_thread: threading.Thread | None = None
_launch_lock = threading.Lock()
_MIN_LAUNCH_GAP_SEC = 18.0


def _stop_backup_processes(pid: Any = None) -> None:
    """Terminate one PID then any orphaned idevicebackup2 (clean single-flight)."""
    if pid:
        try:
            os.kill(int(pid), 15)
            time.sleep(0.35)
            os.kill(int(pid), 9)
        except Exception:
            pass
    try:
        cp = subprocess.run(
            ["pgrep", "-x", "idevicebackup2"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        for p in (cp.stdout or "").split():
            try:
                os.kill(int(p), 15)
            except Exception:
                pass
        time.sleep(0.4)
    except Exception:
        pass


def start_full_backup(
    *,
    device_name: str = "",
    device_id: str = "",
    udid: str = "",
    force_new: bool = False,
    clean_dest: bool = False,
) -> dict[str, Any]:
    """Start or resume full system backup with multi-transport orchestrator."""
    transport = probe_transport()
    uid = udid or transport.get("usb_udid") or transport.get("wifi_udid") or ""
    if not uid:
        # Keep existing session as needs_resume if present — do not fake "running"
        existing = load_session()
        if existing and existing.get("status") not in ("complete", "cancelled", "idle"):
            existing["status"] = "needs_resume"
            existing["phase"] = "awaiting_usb"
            existing["active_transport"] = "none"
            existing["pid"] = None
            save_session(existing)
            return {
                "ok": False,
                "error": "no_device",
                "message": "Plug the iPhone into this Mac with USB to continue the full system backup.",
                "session": session_public_view(existing),
            }
        return {
            "ok": False,
            "error": "no_device",
            "message": "No iPhone on USB or wireless usbmux — plug in to start full system backup.",
        }

    # Identity
    name = device_name
    if not name:
        try:
            cp = subprocess.run(
                ["ideviceinfo", "-u", uid, "-k", "DeviceName"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            name = (cp.stdout or "").strip() or "iPhone"
        except Exception:
            name = "iPhone"

    did = device_id or uid
    durable_seed = max(load_device_high_water(did), load_device_high_water(uid))
    existing = load_session()

    # Toxic dest: no Manifest + repeated Error 205 → start clean folder (keep partials on disk)
    prior_rob = Path("/Volumes/ExternalSSD/CumulousIncoming/full_rob_1784140827")
    if not clean_dest and not force_new:
        try:
            dest_check = Path((existing or {}).get("dest_path") or prior_rob)
            udid_dir = dest_check / uid
            has_manifest = (udid_dir / "Manifest.db").is_file() or (
                udid_dir / "Manifest.plist"
            ).is_file()
            log_p = Path((existing or {}).get("log_path") or "")
            log_txt = log_p.read_text(errors="replace")[-8000:] if log_p.is_file() else ""
            toxic_205 = ("ErrorCode 205" in log_txt or "Error Code 205" in log_txt) and not has_manifest
            if toxic_205:
                clean_dest = True
                force_new = True
        except Exception:
            pass

    if (
        existing
        and existing.get("status")
        in (
            "running",
            "waiting_passcode",
            "needs_resume",
            "handoff",
            "awaiting_network",
            "awaiting_usb",
        )
        and not force_new
        and not clean_dest
    ):
        # Resume same session dest — keep high-water %
        dest = Path(existing["dest_path"])
        label = existing.get("label") or format_backup_label(
            device_name=name, data_kind="FullSystem", backup_number=int(existing.get("backup_number") or 1)
        )
        session = existing
        seed = max(
            float(session.get("last_percent") or 0),
            float(session.get("high_water_percent") or 0),
            durable_seed,
        )
        session["last_percent"] = seed
        session["high_water_percent"] = seed
        session["udid"] = uid
        session["device_id"] = did
        session["device_name"] = name or session.get("device_name")
        if seed > 0:
            save_device_high_water(did, seed, label=str(session.get("label") or ""))
    else:
        n = next_backup_number(did)
        label = format_backup_label(device_name=name, data_kind="FullSystem", backup_number=n)
        root = backup_incoming_root()
        dest = root / label
        dest.mkdir(parents=True, exist_ok=True)
        # Seed from prior partial full_rob tree only if NOT toxic clean_dest
        prior = Path("/Volumes/ExternalSSD/CumulousIncoming/full_rob_1784140827")
        session_note = ""
        if (
            not clean_dest
            and prior.is_dir()
            and not any(dest.iterdir())
        ):
            # Use prior path for seamless continue when tree is healthy enough
            dest = prior
            label = format_backup_label(device_name=name, data_kind="FullSystem", backup_number=n)
        elif clean_dest:
            # Brand-new empty dest — avoids Error 205 poison from incomplete Snapshot/Status
            label = format_backup_label(
                device_name=name, data_kind="FullSystemClean", backup_number=n
            )
            dest = root / label
            dest.mkdir(parents=True, exist_ok=True)
            session_note = "clean_dest_after_205"

        baseline = _dir_stats(dest)
        # Never start a continued tree at 0% if durable/session high-water exists
        # Clean dest starts % from 0 for accuracy of *this* run; keep durable_seed in history only
        start_pct = 0.0 if clean_dest else durable_seed
        session = {
            "session_id": f"bak_{int(time.time())}_{n}",
            "device_id": did,
            "udid": uid,
            "device_name": name,
            "backup_number": n,
            "label": label,
            "data_kind": "FullSystem",
            "dest_path": str(dest),
            "log_path": str(dest.parent / f"{label}.log"),
            "started_at": time.time(),
            "status": "running",
            "phase": "starting",
            "active_transport": "usb" if transport.get("usb") else ("wifi" if transport.get("wifi_usbmux") else "none"),
            "transport_scores": transport.get("scores"),
            "baseline_bytes": baseline.get("bytes") or 0,
            "estimated_total_bytes": max((baseline.get("bytes") or 0) + 3_000_000_000, 12_000_000_000),
            "last_percent": start_pct,
            "high_water_percent": start_pct,
            "prior_attempt_high_water": durable_seed,
            "session_note": session_note,
            "keep_awake_policy": {
                "mac_caffeinate": True,
                "ios_idle_timer_disabled_in_app": True,
                "ios_reassert_interval_sec": 0.25,
                "system_lock_auto_resume": True,
                "cannot_force_unlock": True,
            },
            "verification": {"mode": "incremental_digest_sample", "ok_samples": 0, "fail_samples": 0},
            "pid": None,
        }
        save_session(session)
        if durable_seed > 0 and not clean_dest:
            save_device_high_water(did, durable_seed, label=label)
        if clean_dest:
            # New run — clear durable floor so UI tracks this transfer honestly
            clear_device_high_water(did)
            clear_device_high_water(uid)

    # Repair incomplete tree for clean incremental resume (skip on brand-new empty dest)
    try:
        if not clean_dest:
            session["incremental_repair"] = repair_incremental_backup(
                Path(session["dest_path"]), uid
            )
        else:
            session["incremental_repair"] = {
                "ok": True,
                "actions": ["clean_dest_no_repair_needed"],
            }
    except Exception as e:
        session["incremental_repair"] = {"ok": False, "error": str(e)[:160]}

    # Keep screens awake for the session (restore on complete/cancel)
    try:
        from cumulous.device_power import begin_backup_wake_policy

        session["power"] = begin_backup_wake_policy(
            session_id=str(session.get("session_id") or ""),
            device_name=str(session.get("device_name") or ""),
        )
    except Exception:
        pass

    # Unplug must never cancel — always hand off
    session["unplug_ends_backup"] = False
    session["auto_continue_on_unplug"] = True

    # Launch worker
    _ensure_orchestrator()
    # Immediate process start
    _launch_idevicebackup2(session, transport)
    save_session(session)
    append_history({"event": "start", "label": session.get("label"), "udid": uid})
    return {"ok": True, "session": session_public_view(session)}


def _launch_idevicebackup2(session: dict[str, Any], transport: dict[str, Any] | None = None) -> None:
    """Single-flight launch — never two idevicebackup2 at once (causes -1 protocol errors).

    Uses process-wide + cross-process file lock so Streamlit / CLI / orchestrator
    cannot double-start mobilebackup2.
    """
    import fcntl

    with _launch_lock:
        lock_path = ensure_internal() / "backup_launch.lock"
        with open(lock_path, "a+", encoding="utf-8") as lf:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            try:
                # Re-load disk session so gap check sees other processes' launches
                disk = load_session() or {}
                now = time.time()
                last = float(disk.get("last_launch_at") or session.get("last_launch_at") or 0)
                if last and (now - last) < _MIN_LAUNCH_GAP_SEC:
                    try:
                        cp = subprocess.run(
                            ["pgrep", "-x", "idevicebackup2"],
                            capture_output=True,
                            text=True,
                            timeout=3,
                            check=False,
                        )
                        if (cp.stdout or "").strip():
                            session["pid"] = int((cp.stdout or "").split()[0])
                            session["last_launch_at"] = last
                            return
                    except Exception:
                        return
                    return
                try:
                    cp = subprocess.run(
                        ["pgrep", "-x", "idevicebackup2"],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=False,
                    )
                    if (cp.stdout or "").strip():
                        session["pid"] = int((cp.stdout or "").split()[0])
                        session["last_launch_at"] = now
                        save_session({**disk, **session, "last_launch_at": now})
                        return
                except Exception:
                    pass

                transport = transport or probe_transport()
                uid = session.get("udid") or transport.get("usb_udid") or transport.get("wifi_udid")
                dest = Path(session["dest_path"])
                dest.mkdir(parents=True, exist_ok=True)
                if uid:
                    try:
                        session["incremental_repair"] = repair_incremental_backup(dest, str(uid))
                    except Exception:
                        pass
                log_path = Path(session["log_path"])

                _stop_backup_processes(session.get("pid"))
                time.sleep(0.8)

                use_network = False
                if transport.get("usb"):
                    session["active_transport"] = "usb"
                    uid = transport.get("usb_udid") or uid
                    use_network = False
                elif transport.get("wifi_usbmux"):
                    session["active_transport"] = "wifi"
                    use_network = True
                    uid = transport.get("wifi_udid") or uid
                else:
                    session["active_transport"] = (
                        "cellular" if transport.get("tailscale_ip") else "progressive_api"
                    )
                    session["phase"] = "awaiting_network"
                    session["awaiting_transport"] = True
                    session["last_error"] = None
                    session["transport_scores"] = transport.get("scores")
                    save_session(session)
                    return

                session["awaiting_transport"] = False
                session["transport_scores"] = transport.get("scores")
                # Claim the launch slot before fork
                session["last_launch_at"] = now
                save_session(session)

                cmd: list[str] = []
                if shutil.which("stdbuf"):
                    cmd += ["stdbuf", "-oL", "-eL"]
                cmd += ["idevicebackup2"]
                if uid:
                    cmd += ["-u", str(uid)]
                if use_network:
                    cmd += ["-n"]
                cmd += ["backup", str(dest)]
                if shutil.which("caffeinate"):
                    cmd = ["caffeinate", "-dims", "--"] + cmd
                try:
                    log_f = open(log_path, "ab", buffering=0)
                    log_f.write(
                        f"\n--- launch {time.strftime('%Y-%m-%d %H:%M:%S')} "
                        f"transport={session['active_transport']} ---\n".encode()
                    )
                    proc = subprocess.Popen(
                        cmd,
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    session["pid"] = proc.pid
                    session["status"] = "running"
                    session["phase"] = "receiving"
                    session["last_error"] = None
                    session["last_launch_at"] = time.time()
                    log_f.write(f"pid={proc.pid}\n".encode())
                    save_session(session)
                except Exception as e:
                    session["status"] = "needs_resume"
                    session["last_error"] = str(e)[:200]
                    save_session(session)
            finally:
                try:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass


def _ensure_orchestrator() -> None:
    global _orch_thread
    with _orch_lock:
        if _orch_thread and _orch_thread.is_alive():
            return
        _orch_thread = threading.Thread(target=_orchestrator_loop, name="cumulous-backup-orch", daemon=True)
        _orch_thread.start()


def _orchestrator_loop() -> None:
    """Watch progress, auto-resume on unlock/drop, switch transport when faster."""
    resume_backoff = 2.0
    last_resume_at = 0.0
    while True:
        try:
            session = load_session()
            if not session or session.get("status") in ("complete", "cancelled", "idle"):
                time.sleep(3)
                resume_backoff = 2.0
                continue

            transport = probe_transport()
            session["transport_scores"] = transport.get("scores")
            save_session(session)

            # Always recompute view first (clears sticky waiting_passcode)
            view = session_public_view(session)
            session = load_session() or session
            alive = bool(view.get("process_alive"))
            scores = transport.get("scores") or {}
            active = session.get("active_transport") or "usb"
            log = Path(session.get("log_path") or "")
            parsed = _parse_progress_from_log(log) if log.is_file() else {}
            lock = device_currently_locked(str(session.get("udid") or ""))
            now = time.time()

            # --- Complete ---
            if view.get("status") == "complete" or (parsed.get("phase") == "complete"):
                session["status"] = "complete"
                session["phase"] = "complete"
                session["last_percent"] = 100
                session["waiting_passcode"] = False
                save_session(session)
                if not session.get("_notified_complete"):
                    session["_notified_complete"] = True
                    save_session(session)
                    _notify_complete(session)
                time.sleep(3)
                continue

            # --- USB unplug: NEVER end backup — hand off to best Wi‑Fi / cellular ---
            usb_gone = active == "usb" and not transport.get("usb")
            if usb_gone:
                session["unplug_detected_at"] = now
                # Prefer wireless usbmux, else mark progressive/cellular continue
                if transport.get("wifi_usbmux") or transport.get("tailscale_ip"):
                    session["phase"] = "handoff"
                    session["status"] = "handoff"
                    save_session(session)
                    if alive:
                        try:
                            os.kill(int(session.get("pid") or 0), 15)
                        except Exception:
                            pass
                        time.sleep(1)
                    _launch_idevicebackup2(session, transport)
                    append_history(
                        {
                            "event": "unplug_handoff",
                            "to": session.get("active_transport"),
                            "scores": scores,
                        }
                    )
                    save_session(session)
                    resume_backoff = 2.0
                    continue
                else:
                    # Stay in needs_resume until wifi/cellular appears — do not cancel
                    session["status"] = "needs_resume"
                    session["phase"] = "awaiting_network"
                    session["last_error"] = "USB unplugged — waiting for Wi‑Fi or cellular path"
                    save_session(session)

            # --- Live re-rank: switch when significantly faster transport appears ---
            pref = transport.get("preferred")
            if (
                alive
                and pref
                and pref != active
                and (scores.get(pref) or 0) >= (scores.get(active) or 0) + 15
            ):
                # e.g. USB returns, or wifi much better than cellular progressive
                if pref in ("usb", "wifi") or (pref == "cellular" and not transport.get("usb")):
                    try:
                        os.kill(int(session.get("pid") or 0), 15)
                    except Exception:
                        pass
                    time.sleep(1)
                    _launch_idevicebackup2(session, transport)
                    append_history({"event": "live_rerank", "from": active, "to": pref, "scores": scores})
                    save_session(session)
                    resume_backoff = 2.0
                    continue

            # --- Auto-resume when process dead or stuck in wait with unlock ---
            need_resume = (not alive) and session.get("status") not in ("complete", "cancelled")
            # Also resume if "waiting" but device lockdown says unlocked (false UI)
            # Resume when process died OR stuck waiting without progress for a while
            stuck_wait = (
                view.get("status") == "waiting_passcode"
                and not view.get("disk_growing")
                and (transport.get("usb") or transport.get("wifi_usbmux"))
            )
            # Give CEO time to enter passcode (90s) before kill & retry
            if stuck_wait and alive:
                waited = float(session.get("_wait_since") or 0)
                if waited <= 0:
                    session["_wait_since"] = now
                    save_session(session)
                elif now - waited >= 90:
                    try:
                        os.kill(int(session.get("pid") or 0), 15)
                    except Exception:
                        pass
                    need_resume = True
                    session["_wait_since"] = 0
            else:
                session["_wait_since"] = 0

            if need_resume and (transport.get("usb") or transport.get("wifi_usbmux")):
                # Respect single-flight gap so we never double-launch with start_full_backup
                gap_ok = (now - float(session.get("last_launch_at") or 0)) >= _MIN_LAUNCH_GAP_SEC
                if now - last_resume_at >= resume_backoff and gap_ok:
                    # Always attempt relaunch — user may have just unlocked;
                    # Apple only needs unlock for the handshake, not forever.
                    session["status"] = "running"
                    session["waiting_passcode"] = False
                    session["phase"] = "starting"
                    _launch_idevicebackup2(session, transport)
                    append_history(
                        {
                            "event": "auto_resume",
                            "transport": session.get("active_transport"),
                            "lock": lock.get("locked"),
                            "has_passcode_enabled": lock.get("has_passcode_enabled"),
                            "backoff": resume_backoff,
                        }
                    )
                    save_session(session)
                    last_resume_at = now
                    # Faster retries while waiting for one-time unlock (2s → 12s max)
                    resume_backoff = min(12.0, max(2.0, resume_backoff * 1.25))
            elif alive and view.get("status") == "running":
                resume_backoff = 2.0  # healthy — reset backoff
                session["_wait_since"] = 0

            # Lightweight verification
            dest = Path(session.get("dest_path") or "")
            if dest.is_dir() and int(time.time()) % 30 < 4:
                ver = session.get("verification") or {}
                ok = fail = 0
                samples: list[str] = []
                for root, _d, files in os.walk(dest):
                    for name in files[:3]:
                        fp = Path(root) / name
                        try:
                            if fp.stat().st_size > 0:
                                ok += 1
                            else:
                                fail += 1
                            samples.append(str(fp.relative_to(dest))[:80])
                        except OSError:
                            fail += 1
                        if ok + fail >= 5:
                            break
                    if ok + fail >= 5:
                        break
                ver["ok_samples"] = int(ver.get("ok_samples") or 0) + ok
                ver["fail_samples"] = int(ver.get("fail_samples") or 0) + fail
                ver["last_samples"] = samples[:5]
                ver["last_check"] = time.time()
                session["verification"] = ver
                save_session(session)

            session_public_view(session)
        except Exception as e:
            try:
                s = load_session() or {}
                s["last_error"] = str(e)[:200]
                save_session(s)
            except Exception:
                pass
        time.sleep(3)


def _notify_complete(session: dict[str, Any]) -> None:
    """Mac notification; restore wake policy; phones poll /backup/progress."""
    try:
        from cumulous.device_power import end_backup_wake_policy

        end_backup_wake_policy(reason="complete")
    except Exception:
        pass
    try:
        label = session.get("label") or "backup"
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "Cumulous Backup Complete — {label}" '
                f'with title "Cumulous Backup Complete" sound name "Glass"',
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass
    session["completion_push"] = {
        "title": "Cumulous Backup Complete",
        "body": session.get("label") or "Full system backup finished",
        "at": time.time(),
    }
    session["power_restored"] = True
    save_session(session)


def cancel_backup() -> dict[str, Any]:
    """Explicit cancel only — USB unplug must NOT call this."""
    session = load_session()
    if not session:
        try:
            from cumulous.device_power import end_backup_wake_policy

            end_backup_wake_policy(reason="cancelled")
        except Exception:
            pass
        return {"ok": True, "message": "nothing_running"}
    pid = session.get("pid")
    if pid:
        try:
            os.kill(int(pid), 15)
        except Exception:
            pass
    session["status"] = "cancelled"
    save_session(session)
    try:
        from cumulous.device_power import end_backup_wake_policy

        end_backup_wake_policy(reason="cancelled")
    except Exception:
        pass
    clear_session()
    return {"ok": True, "message": "cancelled", "power_restored": True}
