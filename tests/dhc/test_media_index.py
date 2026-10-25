from core.media_index import merge_sources


def test_merge_prefers_local_file_and_skips_empty_sonarr():
    rows = merge_sources(
        local=[{"id": "L1", "title": "Spirited Away", "popularity": 3, "source": "local"}],
        jellyfin=[{"id": "J1", "title": "Spirited Away", "popularity": 9, "source": "jellyfin"}],
        sonarr=[{"id": "S1", "title": "Empty Show", "popularity": 0, "episodeFileCount": 0}],
    )
    titles = [row["title"] for row in rows]
    assert "Empty Show" not in titles
    assert any(row["source"] == "local" for row in rows)
