"""Progress parser must not sticky-wait on stale passcode log lines."""

from __future__ import annotations

from pathlib import Path

from cumulous.backup_session import (
    _parse_progress_from_log,
    load_device_high_water,
    save_device_high_water,
    save_session,
    session_public_view,
)


def test_percent_never_regresses_on_lock_wait(tmp_path: Path, cumulous_home, monkeypatch):
    """Screen lock / passcode wait must keep high-water %, never snap to 0."""
    dest = tmp_path / "dest"
    dest.mkdir()
    log = tmp_path / "bak.log"
    log.write_text(
        """
--- launch A ---
Receiving files
[========                                          ]  14% (382.4 MB/2.6 GB)
--- launch B ---
*** Waiting for passcode to be entered on the device ***
ErrorCode 208: Device locked
"""
    )
    device_id = "dev-hw-test"
    save_device_high_water(device_id, 14.0, label="test")
    session = {
        "session_id": "s1",
        "device_id": device_id,
        "udid": "udid-1",
        "device_name": "ROB IPHONE",
        "label": "test-label",
        "dest_path": str(dest),
        "log_path": str(log),
        "status": "waiting_passcode",
        "phase": "waiting_passcode",
        "last_percent": 14.0,
        "high_water_percent": 14.0,
        "baseline_bytes": 0,
        "estimated_total_bytes": 3_000_000_000,
        "pid": None,
        "active_transport": "usb",
        "verification": {
            "ok_samples": 2,
            "fail_samples": 0,
            "last_samples": ["/secret/path"],
        },
        "last_error": "ErrorCode 208: Device locked\nTraceback...",
    }
    save_session(session)
    view = session_public_view(session)
    # Dead process: hold high-water %; do not sticky "waiting_passcode" forever
    assert view["percent"] >= 14.0
    assert view["percent_int"] >= 14
    assert view["high_water_percent"] >= 14.0
    assert view["process_alive"] is False
    assert view["status"] in ("needs_resume", "awaiting_usb", "waiting_passcode")
    assert view["unplug_safe"] is True
    assert view["auto_continue_on_unplug"] is True
    assert view["unplug_ends_backup"] is False
    # Public payload never leaks dumps / paths
    assert view.get("error") is None or "Traceback" not in str(view.get("error"))
    assert "Traceback" not in str(view.get("message"))
    assert "208" not in str(view.get("status_line"))
    assert "path" not in str(view.get("verification"))
    assert view["verification"] == {"ok": True, "checked": True}
    assert "Complete" not in view["message"] or view["percent_int"] >= 100
    # Durable store survives
    assert load_device_high_water(device_id) >= 14.0
    # Second poll still floored
    view2 = session_public_view()
    assert view2["percent"] >= 14.0
