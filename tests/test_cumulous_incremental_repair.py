"""Incremental backup Status.plist repair (Error 205)."""

from __future__ import annotations

import plistlib
from pathlib import Path

from cumulous.backup_session import repair_incremental_backup


def test_repair_removes_poison_status_without_manifest(tmp_path: Path):
    """Incomplete tree: no Manifest + bad Status → Status removed (not rewritten to Finished)."""
    udid = "00008120-TEST"
    d = tmp_path / udid
    d.mkdir(parents=True)
    status = {
        "BackupState": "empty",
        "SnapshotState": "uploading",
        "IsFullBackup": True,
        "Version": "3.3",
    }
    with (d / "Status.plist").open("wb") as f:
        plistlib.dump(status, f)
    (d / "Info.plist").write_bytes(plistlib.dumps({"DeviceName": "Test"}))
    # Incomplete Snapshot mid-flight
    snap = d / "Snapshot"
    snap.mkdir()
    (snap / "chunk.bin").write_bytes(b"x" * 16)

    res = repair_incremental_backup(tmp_path, udid)
    assert res["ok"] is True
    assert not (d / "Status.plist").exists(), "poison Status must be removed"
    assert not (d / "Snapshot").exists(), "incomplete Snapshot quarantined"
    assert any(d.glob("Snapshot.partial.*")), "partial kept for recovery"
    assert any("removed_poison_status" in a or "quarantined" in a for a in res["actions"])


def test_repair_keeps_status_when_manifest_present(tmp_path: Path):
    udid = "00008120-OK"
    d = tmp_path / udid
    d.mkdir(parents=True)
    with (d / "Status.plist").open("wb") as f:
        plistlib.dump(
            {
                "BackupState": "new",
                "SnapshotState": "Finished",
                "IsFullBackup": True,
                "Version": "3.3",
            },
            f,
        )
    (d / "Manifest.db").write_bytes(b"sqlite")
    (d / "Info.plist").write_bytes(plistlib.dumps({"DeviceName": "Ok"}))

    res = repair_incremental_backup(tmp_path, udid)
    assert res["ok"] is True
    assert (d / "Status.plist").exists()
    with (d / "Status.plist").open("rb") as f:
        st = plistlib.load(f)
    assert st.get("SnapshotState") == "Finished"
