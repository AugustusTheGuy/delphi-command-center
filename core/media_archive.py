"""Shared zip/hot-cache archive engine for ExternalSSD media (ROMs + video)."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

NOX_ROOT = Path("/Volumes/ExternalSSD/DelphiMedia")
MIN_FREE_GB = 10.0
SESSIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "media_sessions.json"
HOT_STATE_FILE = NOX_ROOT / "hot_cache_state.json"

GLOBAL_HOT_RECENT = 3
PER_SYSTEM_HOT_TOP = 3


@dataclass
class ArchiveEntry:
    id: str
    title: str
    category: str  # rom | movie | tv_episode
    system: str
    year: int | None
    zip_path: str | None
    inner_file: str | None
    hot_path: str | None
    extracted: bool
    on_device: bool
    play_count: int = 0
    play_seconds: int = 0
    rating_rank: int | None = None
    popularity_rank: int | None = None
    emulator: str = ""
    cover_path: str | None = None
    extra: dict[str, Any] | None = None


def nox_available() -> bool:
    return Path("/Volumes/ExternalSSD").exists()


def free_gb(path: Path | None = None) -> float:
    target = path or Path("/Volumes/ExternalSSD")
    if not target.exists():
        target = Path.home()
    try:
        usage = shutil.disk_usage(target)
    except OSError:
        try:
            usage = shutil.disk_usage(Path.home())
        except OSError:
            return 0.0
    return usage.free / (1024 ** 3)


def save_catalog_file(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Write a catalog. A blocked external drive must not take the app down."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = dict(payload)
        body.pop("save_error", None)
        path.write_text(json.dumps(body, indent=2))
        payload.pop("save_error", None)
    except OSError:
        payload["save_error"] = "ExternalSSD catalog could not be saved. The library stays open."
    return payload


def has_min_free_space(min_gb: float = MIN_FREE_GB) -> bool:
    if nox_available():
        return free_gb() >= min_gb
    return free_gb(Path.home()) >= min_gb


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "_", s).strip("_")[:80]


def index_zip(zip_path: Path) -> list[str]:
    if not zip_path.is_file():
        return []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return [n for n in zf.namelist() if not n.endswith("/")]
    except (zipfile.BadZipFile, OSError):
        return []


def unzip_member(zip_path: Path, member: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        out = dest_dir / Path(member).name
        with zf.open(member) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return out


def unzip_all(zip_path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
    return dest_dir


def zip_directory(src_dir: Path, zip_path: Path) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for f in sorted(src_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir))
    return zip_path


def load_sessions() -> dict[str, Any]:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"active": {}, "history": []}


def save_sessions(data: dict[str, Any]) -> None:
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_FILE.write_text(json.dumps(data, indent=2))


def mark_play_start(entry_id: str, hot_path: str) -> None:
    data = load_sessions()
    data["active"][entry_id] = {
        "started": datetime.now().isoformat(),
        "hot_path": hot_path,
    }
    save_sessions(data)


def mark_play_end(entry_id: str) -> None:
    data = load_sessions()
    data["active"].pop(entry_id, None)
    data["history"] = [{"id": entry_id, "ended": datetime.now().isoformat()}] + data.get("history", [])[:200]
    save_sessions(data)


def load_hot_state() -> dict[str, Any]:
    if HOT_STATE_FILE.exists():
        try:
            return json.loads(HOT_STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"pinned": [], "updated_at": None}


def save_hot_state(state: dict[str, Any]) -> None:
    NOX_ROOT.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().isoformat()
    HOT_STATE_FILE.write_text(json.dumps(state, indent=2))


def compute_hot_keep_ids(catalog_entries: list[dict[str, Any]]) -> set[str]:
    """Last 3 played globally + top 3 most-played per system."""
    by_recent = sorted(
        catalog_entries,
        key=lambda e: e.get("last_played") or "",
        reverse=True,
    )
    recent_ids = {e["id"] for e in by_recent[:GLOBAL_HOT_RECENT] if e.get("last_played")}

    per_system: set[str] = set()
    systems = {e.get("system") for e in catalog_entries if e.get("system")}
    for sys in systems:
        sys_entries = [e for e in catalog_entries if e.get("system") == sys]
        sys_entries.sort(key=lambda e: (-e.get("play_count", 0), -e.get("play_seconds", 0)))
        per_system.update(e["id"] for e in sys_entries[:PER_SYSTEM_HOT_TOP] if e.get("play_count", 0) > 0)

    return recent_ids | per_system


def rezip_directory(hot_dir: Path, zip_path: Path) -> bool:
    if not hot_dir.exists():
        return False
    files = list(hot_dir.rglob("*"))
    if not any(f.is_file() for f in files):
        shutil.rmtree(hot_dir, ignore_errors=True)
        return True
    zip_directory(hot_dir, zip_path)
    shutil.rmtree(hot_dir, ignore_errors=True)
    return True


def enforce_hot_cache(
    catalog: list[dict[str, Any]],
    rezip_fn,
) -> dict[str, Any]:
    """
    Re-zip extracted entries not in hot-keep set when disk space is low.
    rezip_fn(entry_dict) -> bool
    """
    keep = compute_hot_keep_ids(catalog)
    rezipped: list[str] = []
    low_space = not has_min_free_space(MIN_FREE_GB)

    for entry in catalog:
        if not entry.get("extracted") or not entry.get("hot_path"):
            continue
        eid = entry["id"]
        if eid in keep and not low_space:
            continue
        if eid in keep and low_space and free_gb() >= MIN_FREE_GB:
            continue
        if rezip_fn(entry):
            rezipped.append(eid)

    state = load_hot_state()
    state["pinned"] = sorted(keep)
    state["rezipped"] = rezipped
    state["free_gb"] = round(free_gb(), 2)
    save_hot_state(state)
    return state


def stale_active_sessions(max_hours: float = 4.0) -> list[str]:
    data = load_sessions()
    cutoff = datetime.now() - timedelta(hours=max_hours)
    stale = []
    for eid, meta in data.get("active", {}).items():
        try:
            started = datetime.fromisoformat(meta["started"])
            if started < cutoff:
                stale.append(eid)
        except (ValueError, KeyError):
            stale.append(eid)
    return stale