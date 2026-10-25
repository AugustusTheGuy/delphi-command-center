from core.typeahead import highlight_title, rank_matches


def test_order_is_required_and_contiguous_wins():
    items = [
        {"id": "1", "title": "cba", "popularity": 100},
        {"id": "2", "title": "abacus", "popularity": 1},
        {"id": "3", "title": "a b c", "popularity": 50},
    ]
    hits = rank_matches("abc", items)
    assert [hit["id"] for hit in hits] == ["2", "3"]


def test_popularity_breaks_equal_matches_and_caps_at_10():
    items = [{"id": str(i), "title": f"Zelda {i}", "popularity": i} for i in range(12)]
    hits = rank_matches("zel", items)
    assert len(hits) == 10
    assert hits[0]["id"] == "11"


def test_highlight_escapes_and_marks_the_slice():
    html = highlight_title("<b>Zelda", [3, 4, 5])
    assert html.startswith("&lt;b&gt;")
    assert "<mark>Zel</mark>" in html


def test_empty_query_returns_nothing():
    assert rank_matches("", [{"id": "1", "title": "Zelda", "popularity": 1}]) == []
