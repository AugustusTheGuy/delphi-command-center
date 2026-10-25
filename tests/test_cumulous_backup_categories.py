"""Backup category verification report."""

from __future__ import annotations

from cumulous.backup_categories import CATEGORY_TAXONOMY, evaluate_categories


def test_taxonomy_has_five_subcategories_each():
    assert len(CATEGORY_TAXONOMY) >= 5
    for cat in CATEGORY_TAXONOMY:
        assert len(cat["subcategories"]) == 5, cat["id"]


def test_evaluate_categories_structure(cumulous_home, monkeypatch):
    # Minimal offline evaluation should not crash
    report = evaluate_categories(device_id="test-device", use_ai=False)
    assert report["ok"] is True
    assert "categories" in report
    assert "summary" in report
    assert "total_backed_up_label" in report["summary"]
    for cat in report["categories"]:
        assert "title" in cat
        assert "verified" in cat
        assert "size_label" in cat
        assert "size_bytes" in cat
        assert len(cat["subcategories"]) == 5
        for sub in cat["subcategories"]:
            assert "title" in sub
            assert "verified" in sub
            assert "size_label" in sub
