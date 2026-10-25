"""CP auto-continue: when ROB iPhone (2) appears on USB, resume photo dual-mirror.

Runs as a long-lived process (nohup). Safe to start multiple times — harvest
is single-flight. Does not delete anything from the phone.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from cumulous.paths import ensure_internal


STATE_FILE = "cp_auto_continue.json"
DEFAULT_DEVICE_IMEI = "354345290021725"
POLL_SEC = 8


def _state_path() -> Path:
    return ensure_internal() / STATE_FILE


def load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_state(data: dict) -> None:
    ensure_internal()
    p = _state_path()
    data["updated_at"] = time.time()
    p.write_text(json.dumps(data, indent=2))


def _load_intent() -> dict:
    p = ensure_internal() / "cp_session_intent.json"
    if not p.exists():
        return {"priority": "photos_first_then_full_system"}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"priority": "photos_first_then_full_system"}


def _save_intent(data: dict) -> None:
    p = ensure_internal() / "cp_session_intent.json"
    data["updated_at"] = time.time()
    p.write_text(json.dumps(data, indent=2))


def tick() -> dict:
    """One poll cycle: photos first, then optional full system; USB→Wi‑Fi→cellular."""
    from cumulous.apple_accounts import list_accounts
    from cumulous.devices import probe_connected_device
    from cumulous.photo_offload import (
        harvest_is_alive,
        harvest_progress,
        load_harvest_state,
        start_device_media_harvest,
        library_status,
    )
    from cumulous.backup_session import load_session, start_full_backup, session_public_view

    st = load_state()
    intent = _load_intent()
    st.setdefault("ticks", 0)
    st["ticks"] = int(st["ticks"]) + 1
    probe = probe_connected_device() or {}
    udid = str(probe.get("udid") or "")
    did = str(probe.get("imei") or probe.get("device_id") or udid or DEFAULT_DEVICE_IMEI)
    name = str(probe.get("display_name") or "")
    was_usb = bool(st.get("was_usb"))
    is_usb = bool(udid)
    usb_edge = is_usb and not was_usb

    # USB re-plug: immediately resume stalled full-system backup (fixes 76% freeze)
    if usb_edge and is_usb:
        bak = load_session() or {}
        bak_status = str(bak.get("status") or "")
        # Do not re-launch if a live process is already waiting for passcode / running
        # (launch lock helps, but skip avoids needless thrash — deepcheck C1/C5/C6)
        try:
            edge_view = session_public_view() or {}
        except Exception:
            edge_view = {}
        edge_alive = bool(edge_view.get("process_alive"))
        leave_live = edge_alive and bak_status in (
            "running",
            "waiting_passcode",
            "handoff",
        )
        if leave_live:
            st["was_usb"] = is_usb
            st["last"] = {
                "action": "usb_edge_leave_live_process",
                "status": bak_status,
                "percent_int": edge_view.get("percent_int"),
            }
            save_state(st)
            return st["last"]
        if bak_status in (
            "needs_resume",
            "awaiting_usb",
            "waiting_passcode",
            "running",
            "error",
            "handoff",
        ) or int(float(bak.get("high_water_percent") or 0)) > 0:
            try:
                fr = start_full_backup(
                    device_id=did,
                    udid=udid,
                    device_name=name or "iPhone",
                )
                st["was_usb"] = is_usb
                st["last"] = {
                    "action": "usb_edge_full_backup_resume",
                    "ok": fr.get("ok"),
                    "message": fr.get("message"),
                    "view": {
                        k: (fr.get("session") or session_public_view() or {}).get(k)
                        for k in ("status", "percent_int", "status_line")
                    },
                }
                save_state(st)
                return st["last"]
            except Exception as e:
                st["last_usb_edge_error"] = str(e)[:200]
    st["was_usb"] = is_usb

    aid = ""
    try:
        for a in list_accounts():
            if a.get("is_ceo") or a.get("apple_id"):
                aid = a.get("apple_id") or ""
                if a.get("is_ceo"):
                    break
    except Exception:
        pass

    harv = load_harvest_state()
    lib = library_status()
    out = {
        "usb": is_usb,
        "device_name": name,
        "device_id": did,
        "udid": udid,
        "harvest_status": harv.get("status"),
        "mirrored": harv.get("mirrored"),
        "dual_ok": harv.get("dual_ok"),
        "library_files": lib.get("file_count"),
        "dual_library": lib.get("mirrored_dual_count"),
        "phase": intent.get("phase") or "waiting_usb_for_photos",
        "priority": intent.get("priority"),
        "action": "idle",
        "usb_edge": usb_edge,
    }

    if not udid:
        out["action"] = "waiting_for_usb"
        intent["phase"] = "waiting_usb_for_photos"
        _save_intent(intent)
        st["last"] = out
        save_state(st)
        return out

    # Phase 1: photo dual-mirror (add-only) — CEO priority
    if harvest_is_alive() or harv.get("status") == "running":
        # Stalled heartbeat: force restart if status=running but no update 3+ min
        try:
            age = time.time() - float(harv.get("updated_at") or 0)
        except Exception:
            age = 0
        if harv.get("status") == "running" and age > 180 and not harvest_is_alive():
            res = start_device_media_harvest(
                device_id=did,
                udid=udid,
                apple_account_id=aid,
                limit=None,
                force=True,
                use_process=True,
            )
            out["action"] = "harvest_force_restart"
            out["start"] = res
            intent["phase"] = "photos_running"
            _save_intent(intent)
            st["last"] = out
            save_state(st)
            return out
        out["action"] = "harvest_running"
        out["progress"] = harvest_progress().get("harvest")
        intent["phase"] = "photos_running"
        _save_intent(intent)
        st["last"] = out
        save_state(st)
        return out

    # Restart photos if complete but gap still large, or USB just plugged in
    gap = 0
    try:
        inv = (lib.get("device_media") or {})
        gap = max(0, int(inv.get("media_total") or 0) - int(lib.get("file_count") or 0))
    except Exception:
        gap = 0
    out["photo_gap"] = gap

    photos_pass_done = st.get("photos_pass_done_for_udid") == udid
    last_fin = float(harv.get("finished_at") or 0)
    stale_complete = harv.get("status") == "complete" and (time.time() - last_fin) > 120
    harv_status = harv.get("status") or ""

    # When harvest just completed, fall through to Phase 2 — do NOT restart forever
    # (old bug: not photos_pass_done → need_photos always True → never reached full system).
    need_photos = False
    if usb_edge:
        need_photos = True
        st.pop("photos_pass_done_for_udid", None)  # new plug = new photos pass
        st.pop("full_backup_started_for_udid", None)
        photos_pass_done = False
    elif harv_status == "complete":
        # Optional later re-pass only if huge remaining gap and already handed off once
        need_photos = bool(photos_pass_done and gap > 5000 and stale_complete)
    elif harv_status in ("error", "idle", "stalled_restart", ""):
        need_photos = not photos_pass_done
    elif harv_status == "running":
        need_photos = False  # handled above via harvest_is_alive
    else:
        need_photos = not photos_pass_done

    if need_photos and intent.get("priority", "").startswith("photos"):
        res = start_device_media_harvest(
            device_id=did,
            udid=udid,
            apple_account_id=aid,
            limit=None,
            force=usb_edge,
            use_process=True,
        )
        out["action"] = "harvest_started" if res.get("started") else (
            "already_running" if res.get("already_running") else "harvest_result"
        )
        out["start"] = {k: res.get(k) for k in ("ok", "started", "already_running") if k in res}
        intent["phase"] = "photos_running"
        _save_intent(intent)
        st["last"] = out
        st["last_start_at"] = time.time()
        save_state(st)
        return out

    # Mark photos pass complete for this plug and hand off to full system
    if harv_status == "complete" or photos_pass_done:
        if harv_status == "complete":
            st["photos_pass_done_for_udid"] = udid
            intent["phase"] = "photos_pass_complete"
            intent["photos_finished_at"] = time.time()
            intent["ask_free_phone"] = intent.get("free_phone") == "ask_when_photo_backup_finishes"
            _save_intent(intent)

        # Phase 2: full system if CEO chose photos_first_then_full_system
        if intent.get("priority") == "photos_first_then_full_system":
            try:
                from cumulous.backup_session import session_public_view, start_full_backup

                view = session_public_view() or {}
                v_status = str(view.get("status") or "")
                proc_alive = bool(view.get("process_alive"))
                # Leave alone while transferring OR while a live process waits for passcode.
                # Re-starting mid-wait thrashing kills the Apple trust prompt (deepcheck C1/C5).
                running_ok = bool(view.get("active")) and v_status in (
                    "running",
                    "handoff",
                    "awaiting_network",
                )
                waiting_live = v_status == "waiting_passcode" and proc_alive
                already_started = st.get("full_backup_started_for_udid") == udid
                if running_ok or waiting_live:
                    out["action"] = (
                        "full_backup_waiting_passcode"
                        if waiting_live
                        else "full_backup_already_active"
                    )
                    out["session"] = {
                        k: view.get(k)
                        for k in ("percent_int", "status_line", "status", "process_alive")
                    }
                    st["full_backup_started_for_udid"] = udid
                elif already_started and v_status in ("complete",):
                    out["action"] = "full_system_already_complete"
                elif (not already_started) or v_status in (
                    "needs_resume",
                    "error",
                    "cancelled",
                    "waiting_passcode",  # only when process dead (waiting_live handled above)
                    "",
                ):
                    fb = start_full_backup(
                        device_id=did,
                        udid=udid,
                        device_name=name or "ROB IPHONE (2)",
                    )
                    sess = fb.get("session") or {}
                    out["full_backup"] = {
                        "ok": fb.get("ok"),
                        "error": fb.get("error"),
                        "message": fb.get("message"),
                        "label": sess.get("label"),
                        "session_id": sess.get("session_id"),
                    }
                    if fb.get("ok"):
                        st["full_backup_started_for_udid"] = udid
                        out["action"] = "full_system_started"
                        intent["phase"] = "full_system_running"
                        _save_intent(intent)
                    else:
                        out["action"] = "full_system_error"
                        out["error"] = str(fb.get("message") or fb.get("error") or "start failed")[:200]
            except Exception as e:
                out["action"] = "full_system_error"
                out["error"] = str(e)[:200]
        else:
            out["action"] = (
                "photos_complete_waiting_ceo_free_phone"
                if intent.get("ask_free_phone")
                else "idle_photos_done"
            )

    st["last"] = out
    save_state(st)
    return out


def run_loop(*, max_hours: float = 12.0) -> None:
    deadline = time.time() + max_hours * 3600
    print(f"[cp_auto_continue] watching USB for up to {max_hours}h", flush=True)
    while time.time() < deadline:
        try:
            r = tick()
            print(
                f"[cp_auto_continue] {time.strftime('%H:%M:%S')} "
                f"usb={r.get('usb')} name={r.get('device_name') or '—'} "
                f"action={r.get('action')} dual={r.get('dual_library')} "
                f"harv={r.get('harvest_status')}",
                flush=True,
            )
        except Exception as e:
            print(f"[cp_auto_continue] error: {e}", flush=True)
        time.sleep(POLL_SEC)
    print("[cp_auto_continue] done", flush=True)


if __name__ == "__main__":
    run_loop()
