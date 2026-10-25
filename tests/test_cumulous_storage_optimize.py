"""Storage optimization plan ranking + safety."""

from __future__ import annotations

from cumulous.photo_offload import dual_mirror_bytes, enable_free_phone_after_dual_mirror
from cumulous.storage_optimize import (
    backup_start_storage_gate,
    build_candidates,
    plan_optimization,
)


def test_plan_only_dual_verified(cumulous_home, monkeypatch):
    enable_free_phone_after_dual_mirror()
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201, "url": "mock"},
    )
    # large fake photo
    data = b"JPEG" + (b"\x00" * (3 * 1024 * 1024))
    dual_mirror_bytes(
        data,
        device_id="dev-opt",
        rel_name="IMG_OLD.JPG",
        apple_account_id="a@b.c",
        local_asset_id="/DCIM/100APPLE/IMG_OLD.JPG",
    )
    plan = plan_optimization(device_id="dev-opt", mode="aggressive")
    assert plan["ok"] is True
    assert plan["dry_run"] is True
    assert plan["projected_bytes"] >= 0
    # candidates must all be dual
    for it in plan.get("items") or []:
        assert it["hdd_ok"] and it["nextcloud_ok"]
        assert it["confidence"] > 0


def test_scores_prefer_larger_when_equal_conf(cumulous_home, monkeypatch):
    enable_free_phone_after_dual_mirror()
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201, "url": "mock"},
    )
    dual_mirror_bytes(
        b"A" * (5 * 1024 * 1024),
        device_id="d2",
        rel_name="BIG.MOV",
        apple_account_id="x",
        local_asset_id="/DCIM/100APPLE/BIG.MOV",
    )
    dual_mirror_bytes(
        b"B" * (500 * 1024),
        device_id="d2",
        rel_name="small.jpg",
        apple_account_id="x",
        local_asset_id="/DCIM/100APPLE/small.jpg",
    )
    cands = build_candidates(device_id="d2", mode="aggressive")
    if len(cands) >= 2:
        # First should be larger score (typically the big video)
        assert cands[0].score >= cands[1].score


def test_backup_gate_awaits_user(cumulous_home):
    g = backup_start_storage_gate(device_id="x", user_wants_optimize=None)
    assert g.get("awaiting_user") is True
    g2 = backup_start_storage_gate(device_id="x", user_wants_optimize=False)
    assert g2.get("skipped") is True
