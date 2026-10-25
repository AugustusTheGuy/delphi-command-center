"""Progressive backup + device bridge on shipped modules."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from cumulous.crypto_vault import open_bytes
from cumulous.device_bridge import fingerprint_files, verify_against_generation
from cumulous.progressive_backup import (
    create_generation,
    current_head,
    decide_strategy,
    get_blob,
    restore_generation,
)


def test_baseline_incremental_restore_verify(cumulous_home):
    device = "iphone-14-pro-max"
    pw = "BackupPass9!"
    base = {
        "photos/a.jpg": b"jpeg-bytes-a",
        "notes/n1.txt": b"note one",
        "sms/thread1.txt": b"sms hello",
    }
    t0 = fingerprint_files(base)
    r1 = create_generation(device, base, pw, categories=["photos", "notes", "sms"], mode="persistent")
    assert r1["status"] == "ok"
    assert r1["strategy"] == "baseline"
    head1 = r1["head"]
    assert current_head(device) == head1

    report = verify_against_generation(device, head1, t0)
    assert report["status"] == "verified"
    assert report["match_rate"] >= 0.999

    restored = restore_generation(device, head1, pw)
    assert restored == base

    # additive only → incremental
    next_files = dict(base)
    next_files["photos/b.jpg"] = b"jpeg-bytes-b"
    r2 = create_generation(device, next_files, pw, categories=["photos", "notes", "sms"])
    assert r2["status"] == "ok"
    assert r2["strategy"] == "incremental"
    assert current_head(device) == r2["head"]
    assert r2["head"] != head1

    restored2 = restore_generation(device, r2["head"], pw)
    assert restored2["photos/b.jpg"] == b"jpeg-bytes-b"
    assert restored2["photos/a.jpg"] == b"jpeg-bytes-a"


def test_deletion_forces_full_manifest_strategy(cumulous_home):
    prev = {"a": "d1", "b": "d2"}
    new = {"a": "d1"}  # b deleted
    assert decide_strategy(prev, new) == "full_manifest"
    assert decide_strategy(None, {"a": "d1"}) == "baseline"
    assert decide_strategy(prev, prev) == "noop"
    assert decide_strategy(prev, {"a": "d1", "b": "d2", "c": "d3"}) == "incremental"


def test_wrong_password_cannot_open_blob(cumulous_home):
    device = "dev-x"
    pw = "RightPass9!"
    files = {"f.txt": b"secret-file"}
    r = create_generation(device, files, pw)
    assert r["status"] == "ok"
    man = r["manifest"]
    digest = man["files"][0]["digest"]
    # get_blob uses open_bytes under the hood — wrong password must fail
    with pytest.raises((InvalidTag, ValueError, Exception)):
        get_blob(device, digest, "WrongPass9!")


def test_verify_mismatch_fails(cumulous_home):
    device = "dev-y"
    pw = "RightPass9!"
    files = {"f.txt": b"aaa"}
    t0 = fingerprint_files({"f.txt": b"bbb"})  # different content
    r = create_generation(device, files, pw)
    report = verify_against_generation(device, r["head"], t0)
    assert report["status"] in ("failed", "partial")
    assert report["mismatched"] or report["match_rate"] < 0.999
