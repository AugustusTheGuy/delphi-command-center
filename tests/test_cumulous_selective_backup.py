"""Selective backup/restore catalog and id expansion."""

from __future__ import annotations

from cumulous.selective_backup import (
    backup_selected,
    build_selectable_catalog,
    expand_ids,
    restore_all_device_data,
    restore_selected,
    save_selection,
)


def test_catalog_has_categories_and_buttons(cumulous_home):
    cat = build_selectable_catalog(device_id="test-device")
    assert cat["ok"] is True
    assert len(cat["categories"]) >= 5
    assert "backup_selected" in cat["button_labels"]
    assert cat["colors"]["backup_green"] == "#007AFF"
    assert cat["colors"]["restore_sky_blue"] == "#007AFF"
    # each category has children + size labels for UI
    for c in cat["categories"]:
        assert c["id"]
        assert c["title"]
        assert "size_label" in c
        assert isinstance(c.get("children"), list)
        for ch in c["children"]:
            assert "size_label" in ch


def test_expand_ids_parent_includes_children(cumulous_home):
    cat = build_selectable_catalog()
    expanded = expand_ids(["photos_videos"], cat)
    assert "photos_videos" in expanded
    assert any(x.startswith("photos_videos.") for x in expanded)


def test_backup_selected_empty(cumulous_home):
    res = backup_selected([], device_id="x")
    assert res["ok"] is False
    assert res["error"] == "nothing_selected"


def test_restore_selected_stages(cumulous_home, monkeypatch):
    # Avoid huge copies — empty photo root is fine
    monkeypatch.setenv("CUMULOUS_FORCE_INTERNAL_VAULT", "1")
    save_selection(["music"])
    res = restore_selected(["music"], device_id="dev")
    assert res["ok"] is True or res.get("status") == "staged_on_mac" or res.get("dest")
    # empty music vault may still create package
    assert "message" in res


def test_restore_all_requires_confirm(cumulous_home):
    res = restore_all_device_data(confirm=False)
    assert res["ok"] is False
    assert res["error"] == "confirm_required"
