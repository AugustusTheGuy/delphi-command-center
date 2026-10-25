"""Local Video Library on ExternalSSD — zip archives, unzip-on-play, VLC (owned media only)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from core.media_archive import (
    MIN_FREE_GB,
    NOX_ROOT,
    ArchiveEntry,
    enforce_hot_cache,
    free_gb,
    has_min_free_space,
    index_zip,
    mark_play_end,
    save_catalog_file,
    mark_play_start,
    nox_available,
    rezip_directory,
    slugify,
    unzip_all,
    unzip_member,
)

VIDEO_ROOT = NOX_ROOT / "Video"
MOVIES_ARCH = VIDEO_ROOT / "Movies" / "archives"
MOVIES_HOT = VIDEO_ROOT / "Movies" / "hot"
TV_ROOT = VIDEO_ROOT / "TV"
CATALOG_FILE = VIDEO_ROOT / "catalog.json"
STATS_FILE = Path(__file__).resolve().parent.parent / "data" / "video_stats.json"

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".webm"}

STREAMING_SERVICES = [
    {"name": "Netflix", "icon": "🎬", "url": "https://www.netflix.com"},
    {"name": "Disney+", "icon": "✨", "url": "https://www.disneyplus.com"},
    {"name": "Max", "icon": "🎥", "url": "https://www.max.com"},
    {"name": "Amazon Prime Video", "icon": "📦", "url": "https://www.amazon.com/gp/video/storefront"},
    {"name": "Apple TV+", "icon": "🍎", "url": "https://tv.apple.com"},
    {"name": "Hulu", "icon": "🟢", "url": "https://www.hulu.com"},
    {"name": "Paramount+", "icon": "⛰️", "url": "https://www.paramountplus.com"},
    {"name": "Peacock", "icon": "🦚", "url": "https://www.peacocktv.com"},
    {"name": "YouTube", "icon": "▶️", "url": "https://www.youtube.com"},
    {"name": "Crunchyroll", "icon": "🍥", "url": "https://www.crunchyroll.com"},
]


def _ensure_layout() -> None:
    MOVIES_ARCH.mkdir(parents=True, exist_ok=True)
    MOVIES_HOT.mkdir(parents=True, exist_ok=True)
    TV_ROOT.mkdir(parents=True, exist_ok=True)


def _load_stats() -> dict[str, Any]:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _save_stats(stats: dict[str, Any]) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, indent=2))


def _pick_video_member(members: list[str]) -> str | None:
    for m in members:
        if Path(m).suffix.lower() in VIDEO_EXTENSIONS:
            return m
    return None


def scan_video_archives() -> list[ArchiveEntry]:
    _ensure_layout()
    entries: list[ArchiveEntry] = []
    stats = _load_stats()

    for zip_path in MOVIES_ARCH.rglob("*.zip"):
        title = zip_path.stem.replace("_", " ").title()
        eid = f"movie__{slugify(title)}"
        members = index_zip(zip_path)
        inner = _pick_video_member(members)
        hot_dir = MOVIES_HOT / eid
        extracted = hot_dir.exists() and any(hot_dir.iterdir())
        sm = stats.get(eid, {})
        entries.append(ArchiveEntry(
            id=eid,
            title=title,
            category="movie",
            system="Movie",
            year=None,
            zip_path=str(zip_path),
            inner_file=inner,
            hot_path=str(hot_dir) if extracted else None,
            extracted=extracted,
            on_device=True,
            play_count=sm.get("count", 0),
            play_seconds=sm.get("seconds", 0),
        ))

    for zip_path in TV_ROOT.rglob("*.zip"):
        rel = zip_path.relative_to(TV_ROOT)
        parts = list(rel.parts)
        show = parts[0] if parts else "Unknown"
        season = next((p for p in parts if p.lower().startswith("season")), "Season_01")
        ep_name = zip_path.stem
        title = f"{show} — {season} — {ep_name}"
        eid = f"tv__{slugify(show)}__{slugify(season)}__{slugify(ep_name)}"
        members = index_zip(zip_path)
        inner = _pick_video_member(members)
        hot_dir = TV_ROOT / show / season / "hot" / eid
        extracted = hot_dir.exists() and any(hot_dir.iterdir())
        sm = stats.get(eid, {})
        entries.append(ArchiveEntry(
            id=eid,
            title=title,
            category="tv_episode",
            system="TV",
            year=None,
            zip_path=str(zip_path),
            inner_file=inner,
            hot_path=str(hot_dir) if extracted else None,
            extracted=extracted,
            on_device=True,
            play_count=sm.get("count", 0),
            play_seconds=sm.get("seconds", 0),
            extra={"show": show, "season": season, "episode": ep_name},
        ))

    for path in VIDEO_ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and "hot" not in path.parts:
            title = path.stem.replace("_", " ").title()
            eid = f"loose__{slugify(title)}"
            sm = stats.get(eid, {})
            entries.append(ArchiveEntry(
                id=eid,
                title=title,
                category="movie" if "Movies" in path.parts else "tv_episode",
                system="Movie" if "Movies" in path.parts else "TV",
                year=None,
                zip_path=None,
                inner_file=str(path),
                hot_path=None,
                extracted=True,
                on_device=True,
                play_count=sm.get("count", 0),
                play_seconds=sm.get("seconds", 0),
            ))

    return entries


def build_catalog() -> dict[str, Any]:
    if not nox_available():
        return {"entries": [], "note": "ExternalSSD not mounted"}
    try:
        entries = scan_video_archives()
    except OSError:
        return {
            "entries": [],
            "save_error": "ExternalSSD catalog could not be read. The library stays open.",
        }
    rows = [asdict(e) for e in entries]
    payload = {
        "updated_at": datetime.now().isoformat(),
        "nox_free_gb": round(free_gb(), 2),
        "entries": rows,
    }
    return save_catalog_file(CATALOG_FILE, payload)


def ensure_video_extracted(entry: dict[str, Any]) -> tuple[bool, str, str | None]:
    if entry.get("inner_file") and not entry.get("zip_path"):
        p = entry["inner_file"]
        if Path(p).exists():
            return True, "Loose file", p

    zip_path = entry.get("zip_path")
    if not zip_path or not Path(zip_path).exists():
        return False, "Video not on ExternalSSD", None

    hot_dir = Path(entry.get("hot_path") or MOVIES_HOT / entry["id"])
    for f in hot_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            return True, "Hot cache", str(f)

    if not has_min_free_space(MIN_FREE_GB):
        run_maintenance_hook(force_rezip=True)

    zp = Path(zip_path)
    members = index_zip(zp)
    inner = entry.get("inner_file") or _pick_video_member(members)
    hot_dir.mkdir(parents=True, exist_ok=True)
    if inner:
        out = unzip_member(zp, inner, hot_dir)
        return True, "Extracted episode/movie", str(out)
    unzip_all(zp, hot_dir)
    for f in hot_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            return True, "Extracted archive", str(f)
    return False, "No video in zip", None


def play_vlc(path: str, entry_id: str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, "File missing"
    mark_play_start(entry_id, str(p.parent))
    vlc_paths = ["/Applications/VLC.app", "VLC"]
    for cmd in (["open", "-a", "VLC", str(p)], ["vlc", str(p)]):
        try:
            subprocess.Popen(cmd, start_new_session=True)
            stats = _load_stats()
            stats[entry_id] = stats.get(entry_id, {})
            stats[entry_id]["count"] = stats[entry_id].get("count", 0) + 1
            stats[entry_id]["last_played"] = datetime.now().isoformat()
            _save_stats(stats)
            return True, f"Playing in VLC: {p.name}"
        except OSError:
            continue
    return False, "VLC not installed — brew install --cask vlc"


def launch_streaming(url: str) -> tuple[bool, str]:
    try:
        subprocess.Popen(["open", url], start_new_session=True)
        return True, "Opened streaming service"
    except OSError as e:
        return False, str(e)


def rezip_video_entry(entry: dict[str, Any]) -> bool:
    hot = entry.get("hot_path")
    zip_p = entry.get("zip_path")
    if not hot or not zip_p:
        return False
    return rezip_directory(Path(hot), Path(zip_p))


def run_maintenance_hook(force_rezip: bool = False) -> dict[str, Any]:
    catalog = build_catalog()

    def _rezip(e: dict[str, Any]) -> bool:
        if not e.get("extracted"):
            return False
        ok = rezip_video_entry(e)
        if ok:
            e["extracted"] = False
            e["hot_path"] = None
        return ok

    try:
        state = enforce_hot_cache(catalog.get("entries", []), _rezip)
    except OSError:
        catalog["maintenance"] = {"rezipped": []}
        catalog["save_error"] = "ExternalSSD catalog could not be saved. The library stays open."
        return catalog
    catalog["maintenance"] = state
    return save_catalog_file(CATALOG_FILE, catalog)


def most_watched_movies(limit: int = 8) -> list[dict[str, Any]]:
    catalog = build_catalog()
    movies = [e for e in catalog.get("entries", []) if e.get("category") == "movie"]
    movies.sort(key=lambda e: (-e.get("play_count", 0), -e.get("play_seconds", 0)))
    return movies[:limit]


def shows_index() -> dict[str, list[dict[str, Any]]]:
    catalog = build_catalog()
    shows: dict[str, list[dict[str, Any]]] = {}
    for e in catalog.get("entries", []):
        if e.get("category") != "tv_episode":
            continue
        show = (e.get("extra") or {}).get("show", "Unknown")
        shows.setdefault(show, []).append(e)
    return shows


def finish_play(entry_id: str) -> dict[str, Any]:
    mark_play_end(entry_id)
    return run_maintenance_hook()