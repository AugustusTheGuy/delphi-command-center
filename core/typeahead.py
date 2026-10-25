"""Shared typeahead ranking for library search."""

from __future__ import annotations

import html


def _match(query: str, title: str) -> tuple[list[int], int, int, int] | None:
    folded = title.casefold()
    found = folded.find(query)
    if found >= 0:
        return list(range(found, found + len(query))), 2, found, len(query)
    positions: list[int] = []
    cursor = 0
    for char in query:
        found = folded.find(char, cursor)
        if found < 0:
            return None
        positions.append(found)
        cursor = found + 1
    start = positions[0]
    span = positions[-1] - start + 1
    return positions, 1, start, span


def rank_matches(query: str, items: list[dict], limit: int = 10) -> list[dict]:
    needle = query.casefold().strip()
    if not needle:
        return []
    scored: list[tuple] = []
    for item in items:
        title = str(item.get("title") or "")
        matched = _match(needle, title)
        if matched is None:
            continue
        positions, kind, start, span = matched
        popularity = float(item.get("popularity") or 0)
        scored.append((kind, -start, -span, popularity, title.casefold(), item, positions))
    scored.sort(key=lambda row: row[4])
    scored.sort(key=lambda row: (row[0], row[1], row[2], row[3]), reverse=True)
    hits: list[dict] = []
    for row in scored[:limit]:
        hit = dict(row[5])
        hit["positions"] = row[6]
        hits.append(hit)
    return hits


def highlight_title(title: str, positions: list[int]) -> str:
    marked = set(positions)
    parts: list[str] = []
    index = 0
    while index < len(title):
        if index in marked:
            end = index
            while end < len(title) and end in marked:
                end += 1
            parts.append("<mark>" + html.escape(title[index:end]) + "</mark>")
            index = end
        else:
            end = index
            while end < len(title) and end not in marked:
                end += 1
            parts.append(html.escape(title[index:end]))
            index = end
    return "".join(parts)
