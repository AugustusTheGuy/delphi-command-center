"""Cumulous Photos catalog + tagging (Photos.app clone foundation)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from cumulous.photo_library import display_policy, list_assets, scan_library
from cumulous.photo_offload import dual_mirror_bytes, enable_free_phone_after_dual_mirror, photo_library_root
from cumulous.photo_tagging import enrich_file, get_tags, search_by_query


def _jpeg_bytes(color=(30, 120, 200)) -> bytes:
    im = Image.new("RGB", (64, 48), color=color)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_display_policy_blocks_apple_photos_placeholders():
    p = display_policy()
    assert p["apple_photos_app"]["can_show_mac_hdd_as_placeholders"] is False
    assert p["strategy"] == "cumulous_photos_clone"


def test_enrich_file_has_dimensions_and_keywords(cumulous_home, tmp_path):
    p = tmp_path / "shot.jpg"
    p.write_bytes(_jpeg_bytes())
    rec = enrich_file(p, digest="abc123", filename="shot.jpg", run_vision=False, run_geocode=False)
    assert rec["dimensions"]["width"] == 64
    assert rec["dimensions"]["height"] == 48
    assert rec["date_source"] in ("file_mtime", "exif")
    assert isinstance(rec["keywords"], list)
    assert rec["vision"]["status"] in ("deferred", "skipped", "pending", "ok", "error")


def test_dual_mirror_indexes_and_tags(cumulous_home, monkeypatch):
    enable_free_phone_after_dual_mirror()
    monkeypatch.setattr(
        "cumulous.nextcloud_client.nextcloud_reachable",
        lambda cfg=None: {"ok": True},
    )
    monkeypatch.setattr(
        "cumulous.nextcloud_client.upload_bytes",
        lambda remote_rel, data, cfg=None: {"ok": True, "status": 201},
    )
    monkeypatch.setenv("CUMULOUS_PHOTO_VISION", "0")
    monkeypatch.setenv("CUMULOUS_DISABLE_GEOCODE", "1")

    res = dual_mirror_bytes(
        _jpeg_bytes(),
        device_id="dev-photos",
        rel_name="IMG_1001.JPG",
        apple_account_id="acct@example.test",
        local_asset_id="ph://1001",
    )
    assert res["ok"] is True
    digest = res["digest"]
    tags = get_tags(digest)
    assert tags is not None
    assert tags.get("dimensions", {}).get("width") == 64

    scan = scan_library(enrich=False)
    assert scan["ok"] is True
    lib = list_assets(limit=50)
    assert lib["total"] >= 1
    digests = {i["digest"] for i in lib["items"]}
    assert digest in digests

    # library root under test home isolation
    root = photo_library_root()
    assert root.exists()
