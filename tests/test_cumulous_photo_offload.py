"""Dual-mirror HDD + Nextcloud gate for phone deletion queue."""

from __future__ import annotations

from cumulous.photo_offload import (
    dual_mirror_bytes,
    enable_free_phone_after_dual_mirror,
    load_deletion_queue,
    load_prefs,
    pending_deletions_for_device,
)


def test_dual_mirror_hdd_always_and_queue_when_nc_mocked(cumulous_home, monkeypatch):
    enable_free_phone_after_dual_mirror()
    prefs = load_prefs()
    assert prefs["free_phone_storage_after_backup"] is True
    assert prefs["require_dual_mirror_before_delete"] is True

    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201, "url": "mock"},
    )

    res = dual_mirror_bytes(
        b"fake-jpeg-bytes",
        device_id="dev1",
        rel_name="IMG_0001.JPG",
        apple_account_id="user@example.test",
        local_asset_id="ph://1",
    )
    assert res["hdd"]["ok"] is True
    assert res["dual_ok"] is True
    assert res["safe_to_delete_on_device"] is True
    q = pending_deletions_for_device("dev1")
    assert any(i.get("digest") == res["digest"] for i in q)


def test_no_delete_queue_if_nextcloud_fails(cumulous_home, monkeypatch):
    enable_free_phone_after_dual_mirror()
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": False, "error": "down"},
    )
    res = dual_mirror_bytes(
        b"x",
        device_id="dev2",
        rel_name="a.png",
        apple_account_id="a@b.c",
    )
    assert res["hdd"]["ok"] is True
    assert res["dual_ok"] is False
    assert res["safe_to_delete_on_device"] is False
    assert pending_deletions_for_device("dev2") == []
