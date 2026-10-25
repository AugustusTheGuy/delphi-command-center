"""Small search field with a 10-row drop-down."""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_FRONTEND = Path(__file__).resolve().parent / "typeahead_frontend"
_component = components.declare_component("dhc_typeahead", path=str(_FRONTEND))


def typeahead_bar(items: list[dict], key: str):
    slim = [
        {
            "id": item.get("id"),
            "title": item.get("title") or "",
            "popularity": item.get("popularity") or 0,
            "system": item.get("system") or "",
            "on_device": bool(item.get("on_device", True)),
            "source": item.get("source") or "",
        }
        for item in items
    ]
    return _component(items=slim, key=key, default=None)
