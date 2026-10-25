"""USB-gated device delete + add-only vault policy."""

from __future__ import annotations

import hashlib

from cumulous.photo_offload import (
    dual_mirror_bytes,
    enable_free_phone_after_dual_mirror,
    freeable_on_device,
    load_mirror_index,
    mark_deleted_on_device,
    request_device_delete,
    request_device_delete_all_freeable,
    set_download_and_keep_originals,
    load_prefs,
)


def test_request_device_delete_ios_no_usb(cumulous_home, monkeypatch):
    enable_free_phone_after_dual_mirror()
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201, "url": "mock"},
    )
    res = dual_mirror_bytes(
        b"ios-delete-photo",
        device_id="dev-ios",
        rel_name="IMG_IOS.JPG",
        apple_account_id="a@b.c",
        local_asset_id="ph://local-1",
    )
    dig = res["digest"]
    out = request_device_delete(dig, source="ios", require_usb=False)
    assert out["ok"] is True
    assert out.get("client_should_delete") or out.get("queued")
    # vault still present
    assert dig in (load_mirror_index().get("items") or {})


def test_skip_existing_digest_only_preserves_vault(cumulous_home, monkeypatch):
    """Same content twice → one vault object; new content always adds."""
    enable_free_phone_after_dual_mirror()
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201, "url": "mock"},
    )
    a = dual_mirror_bytes(b"same-bytes", device_id="d1", rel_name="A.JPG", apple_account_id="x")
    b = dual_mirror_bytes(b"same-bytes", device_id="d1", rel_name="B.JPG", apple_account_id="x")
    c = dual_mirror_bytes(b"other-bytes", device_id="d1", rel_name="A.JPG", apple_account_id="x")
    assert a["digest"] == b["digest"]
    assert a["digest"] != c["digest"]
    items = load_mirror_index().get("items") or {}
    assert a["digest"] in items
    assert c["digest"] in items
    assert hashlib.sha256(b"same-bytes").hexdigest() == a["digest"]


def test_freeable_and_mark_deleted(cumulous_home, monkeypatch):
    enable_free_phone_after_dual_mirror()
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201, "url": "mock"},
    )
    res = dual_mirror_bytes(b"free-me", device_id="d2", rel_name="F.JPG", apple_account_id="x")
    free = freeable_on_device(device_id="d2", dual_only=True)
    assert any(x.get("digest") == res["digest"] for x in free)
    mark_deleted_on_device(res["digest"])
    free2 = freeable_on_device(device_id="d2", dual_only=True)
    assert not any(x.get("digest") == res["digest"] for x in free2)


def test_download_and_keep_originals_disables_free_phone(cumulous_home):
    prefs = set_download_and_keep_originals(True)
    assert prefs["download_and_keep_originals"] is True
    assert prefs["free_phone_storage_after_backup"] is False
    prefs2 = load_prefs()
    assert prefs2["download_and_keep_originals"] is True


def test_delete_all_usb_gate(cumulous_home, monkeypatch):
    monkeypatch.setattr(
        "cumulous.photo_offload.usb_device_present",
        lambda: {"ok": False, "usb": False, "probe": {}, "udid": ""},
    )
    out = request_device_delete_all_freeable(source="mac")
    assert out["ok"] is False
    assert out.get("error") == "usb_required"
