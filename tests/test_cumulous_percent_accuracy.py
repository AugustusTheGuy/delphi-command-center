"""Backup percent must track real console + disk evidence, not stale high-water."""

from __future__ import annotations

from pathlib import Path

from cumulous.backup_session import (
    _compute_accurate_percent,
    _parse_progress_from_log,
    _parse_size_to_bytes,
    clear_device_high_water,
    load_device_high_water,
    save_device_high_water,
    save_session,
    session_public_view,
)


def test_parse_size_labels():
    assert abs((_parse_size_to_bytes("382.4 MB") or 0) - 382.4e6) < 1e3
    assert abs((_parse_size_to_bytes("2.6 GB") or 0) - 2.6e9) < 1e5
    assert _parse_size_to_bytes("10 Bytes") == 10.0
    assert _parse_size_to_bytes("") is None


def test_stale_high_water_recalibrates_to_disk():
    """Orphan 14% high-water must not win over real disk evidence."""
    parsed = {
        "live_percent": None,
        "session_best_percent": None,
        "has_console_progress": False,
        "receiving": False,
        "phase": "needs_resume",
        "bytes_done": None,
        "bytes_total": None,
    }
    # 9.3 GB on disk, 12.4 GB estimate → ~75%
    pct, meta = _compute_accurate_percent(
        parsed=parsed,
        disk_bytes=9_300_000_000,
        baseline=9_000_000_000,
        estimated_total=12_400_000_000,
        session_high=14.0,
    )
    assert pct >= 70.0
    assert pct <= 99.0
    assert meta["chosen"] in ("evidence_recalibrate", "max_evidence_and_high_water")
    assert meta["signals"].get("disk_absolute", 0) >= 70


def test_clear_device_high_water_resets_not_sets_100(cumulous_home):
    """deepcheck C3: clear must delete durable floor, never write 100%."""
    did = "dev-clear-hw"
    save_device_high_water(did, 55.0, label="t")
    assert load_device_high_water(did) >= 55.0
    clear_device_high_water(did)
    assert load_device_high_water(did) == 0.0
    save_device_high_water(did, 88.0, completed=True)
    assert load_device_high_water(did) == 100.0
    # Mid-run save must not store durable 100
    save_device_high_water(did, 100.0, completed=False)
    assert load_device_high_water(did) <= 99.9
    clear_device_high_water(did)
    assert load_device_high_water(did) == 0.0


def test_live_console_scaled_not_raw_segment_percent():
    """Segment 22% of 2.6GB is not overall 22% of a 12GB backup — scale by size."""
    parsed = {
        "live_percent": 22.0,
        "session_best_percent": 22.0,
        "has_console_progress": True,
        "receiving": True,
        "phase": "receiving",
        "bytes_done": 0.5e9,
        "bytes_total": 2.6e9,
        "live_bytes_total": 2.6e9,
        "live_segment_tiny": False,
    }
    pct, meta = _compute_accurate_percent(
        parsed=parsed,
        disk_bytes=1e9,
        baseline=0,
        estimated_total=12e9,
        session_high=10.0,
    )
    # disk 1/12 ≈ 8.3%, floor 10% → overall around floor; not raw 22%
    assert pct >= 10.0
    assert pct < 22.0
    assert meta["chosen"] == "disk_and_scaled_console"
    assert "console_live_scaled" in meta["signals"] or "disk_absolute" in meta["signals"]


def test_tiny_segment_99_does_not_hang_overall():
    """~8MB domain bars hit 99% constantly — must not pin overall at 99."""
    parsed = {
        "live_percent": 99.0,
        "session_best_percent": None,  # no meaningful large mid-progress
        "has_console_progress": True,
        "receiving": True,
        "phase": "receiving",
        "bytes_done": 7.8e6,
        "bytes_total": 7.9e6,
        "live_bytes_done": 7.8e6,
        "live_bytes_total": 7.9e6,
        "live_segment_tiny": True,
        "largest_meaningful_total": 4.0e9,
    }
    pct, meta = _compute_accurate_percent(
        parsed=parsed,
        disk_bytes=40e9,
        baseline=0,
        estimated_total=50e9,
        session_high=99.0,  # poison from prior tiny segments
        device_data_used=12e9,
    )
    assert pct < 99.0, pct
    assert pct <= 92.0  # disk progress cap
    assert pct >= 80.0  # soft-drop keeps high-80s class or disk ~80%
    assert "console_live_ignored_tiny" in meta["signals"]
    assert meta["signals"].get("disk_absolute", 0) > 0


def test_public_view_climbs_with_disk(tmp_path: Path, cumulous_home):
    dest = tmp_path / "dest"
    dest.mkdir()
    # Create ~40MB of fake payload so disk stats are non-zero
    blob = dest / "data.bin"
    blob.write_bytes(b"\0" * (40 * 1024 * 1024))
    log = tmp_path / "empty.log"
    log.write_text("--- launch now ---\nStarting backup...\n")
    save_device_high_water("dev-acc", 5.0, label="t")
    session = {
        "session_id": "acc1",
        "device_id": "dev-acc",
        "udid": "u1",
        "device_name": "Test",
        "label": "lab",
        "dest_path": str(dest),
        "log_path": str(log),
        "status": "needs_resume",
        "phase": "starting",
        "last_percent": 5.0,
        "high_water_percent": 5.0,
        "baseline_bytes": 0,
        "estimated_total_bytes": 100 * 1024 * 1024,  # 100 MB → disk ~40%
        "pid": None,
        "active_transport": "usb",
    }
    save_session(session)
    view = session_public_view(session)
    assert view["percent"] >= 30.0  # ~40% of 100MB
    assert view["percent"] < 100.0
    assert view["percent_int"] == int(round(view["percent"]))
