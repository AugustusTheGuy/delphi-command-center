"""Video search index: local files, Jellyfin, and Sonarr series already on disk."""

from __future__ import annotations

import time
from typing import Any

import requests

from core.media_services import jellyfin_items_url, load_media_services, sonarr_series_url
from core.ttl_cache import TtlCache
from core.video_library import VIDEO_EXTENSIONS, VIDEO_ROOT, build_catalog

VIDEO_TTL = 120.0
_VIDEO_CACHE = TtlCache(VIDEO_TTL)


def merge_sources(local: list[dict], jellyfin: list[dict], sonarr: list[dict]) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple] = set()
    for row in list(local) + list(jellyfin):
        title = str(row.get("title") or "")
        year = row.get("year")
        key = (title.casefold(), year)
        if year is not None and key in seen:
            continue
        if year is not None:
            seen.add(key)
        rows.append(row)
    for row in sonarr:
        count = int(row.get("episodeFileCount") or 0)
        if count <= 0:
            continue
        item = dict(row)
        item["popularity"] = count
        item["source"] = "sonarr"
        rows.append(item)
    return rows


def _local_rows() -> list[dict]:
    rows: list[dict] = []
    try:
        catalog = build_catalog()
    except OSError:
        catalog = {"entries": []}
    for entry in catalog.get("entries", []):
        rows.append({
            "id": entry.get("id") or entry.get("title"),
            "title": entry.get("title") or "",
            "popularity": entry.get("play_seconds") or 0,
            "source": "local",
            "year": entry.get("year"),
            "path": entry.get("inner_file") or entry.get("zip_path"),
            "kind": "catalog",
        })
    if VIDEO_ROOT.exists():
        try:
            video_paths = list(VIDEO_ROOT.rglob("*"))
        except OSError:
            video_paths = []
        for path in video_paths:
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            if "hot" in path.parts:
                continue
            rows.append({
                "id": str(path),
                "title": path.stem,
                "popularity": 0,
                "source": "local",
                "year": None,
                "path": str(path),
                "kind": "file",
            })
    return rows


def _get_json(url: str, headers: dict[str, str]) -> Any:
    response = requests.get(url, headers=headers, timeout=3)
    response.raise_for_status()
    return response.json()


def fetch_jellyfin() -> tuple[list[dict], str]:
    services = load_media_services()
    base = services["jellyfin_url"].rstrip("/")
    key = services["jellyfin_api_key"]
    if not base or not key:
        return [], "Jellyfin is not connected."
    try:
        payload = _get_json(
            jellyfin_items_url(base),
            {"X-Emby-Token": key},
        )
    except requests.RequestException:
        return [], "Jellyfin is not connected."
    rows = []
    for item in payload.get("Items", []) if isinstance(payload, dict) else []:
        rows.append({
            "id": item.get("Id"),
            "title": item.get("Name") or "",
            "popularity": item.get("PlayCount") or 0,
            "source": "jellyfin",
            "year": item.get("ProductionYear"),
        })
    return rows, ""


def fetch_sonarr() -> tuple[list[dict], str]:
    services = load_media_services()
    base = services["sonarr_url"].rstrip("/")
    key = services["sonarr_api_key"]
    if not base or not key:
        return [], ""
    try:
        payload = _get_json(sonarr_series_url(base), {"X-Api-Key": key})
    except requests.RequestException:
        return [], ""
    rows = []
    for series in payload if isinstance(payload, list) else []:
        stats = series.get("statistics") or {}
        rows.append({
            "id": series.get("id"),
            "title": series.get("title") or "",
            "episodeFileCount": stats.get("episodeFileCount") or 0,
            "year": series.get("year"),
            "path": series.get("path") or "",
        })
    return rows, ""


def build_video_index(force: bool = False, now: float | None = None) -> tuple[list[dict], str]:
    clock = time.time() if now is None else now
    if not force:
        cached = _VIDEO_CACHE.get("video", clock)
        if cached is not None:
            return cached
    local = _local_rows()
    jellyfin, jellyfin_message = fetch_jellyfin()
    sonarr, _sonarr_message = fetch_sonarr()
    payload = (merge_sources(local, jellyfin, sonarr), jellyfin_message)
    _VIDEO_CACHE.put("video", payload, clock)
    return payload


def clear_video_cache() -> None:
    _VIDEO_CACHE.clear()
