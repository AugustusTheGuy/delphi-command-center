"""Cumulous Photos — library catalog, thumbs, albums (Photos.app-like).

Display strategy: Apple does not allow third-party HDD photos inside the
system Photos app as iCloud placeholders. Cumulous Photos is the in-app
clone used on Mac + iOS, synced from dual-mirrored backup originals.
"""

from __future__ import annotations

import hashlib
import io
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal
from cumulous.photo_offload import MEDIA_EXT, is_media, load_mirror_index, photo_library_root
from cumulous.photo_tagging import enrich_and_store, get_tags, search_by_query


def thumbs_root() -> Path:
    d = ensure_internal() / "photo_thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def catalog_path() -> Path:
    return ensure_internal() / "photo_catalog.json"


def _load_catalog() -> dict[str, Any]:
    p = catalog_path()
    if not p.exists():
        return {"assets": {}, "scanned_at": 0}
    try:
        import json

        return json.loads(p.read_text())
    except Exception:
        return {"assets": {}, "scanned_at": 0}


def _save_catalog(data: dict[str, Any]) -> None:
    import json

    ensure_internal()
    data["scanned_at"] = time.time()
    p = catalog_path()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def digest_for_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def scan_library(*, enrich: bool = True, limit: int | None = None) -> dict[str, Any]:
    """Walk CumulousPhotos + merge mirror index; optional tag enrichment."""
    root = photo_library_root()
    cat = _load_catalog()
    assets: dict[str, Any] = cat.setdefault("assets", {})
    mirror = (load_mirror_index().get("items") or {})
    added = 0
    updated = 0
    enriched = 0

    # Seed from mirror index first (known digests + paths)
    for digest, item in mirror.items():
        path_s = item.get("hdd_path") or ""
        p = Path(path_s) if path_s else None
        if p and p.is_file():
            rec = assets.get(digest) or {}
            try:
                rel = str(p.relative_to(root))
            except Exception:
                rel = p.name
            rec.update(
                {
                    "digest": digest,
                    "path": str(p),
                    "rel": rel,
                    "name": item.get("name") or p.name,
                    "device_id": item.get("device_id"),
                    "apple_account_id": item.get("apple_account_id"),
                    "size": item.get("size") or p.stat().st_size,
                    "hdd_ok": item.get("hdd_ok"),
                    "nextcloud_ok": item.get("nextcloud_ok"),
                    "safe_to_delete_on_device": item.get("safe_to_delete_on_device"),
                    "media_type": _media_type(p),
                    "updated_at": time.time(),
                }
            )
            assets[digest] = rec
            updated += 1

    # Walk disk for anything not in mirror
    count_walk = 0
    for dirpath, _dirs, files in os.walk(root):
        # skip thumbs
        if "/.cumulous" in dirpath or dirpath.endswith("photo_thumbs"):
            continue
        for name in files:
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if not is_media(p):
                continue
            count_walk += 1
            if limit is not None and count_walk > limit:
                break
            try:
                # Prefer name prefix digest if dual_mirror style: abcd1234_filename
                digest = None
                if "_" in name and len(name.split("_", 1)[0]) == 12:
                    # find full digest from catalog/mirror by prefix
                    prefix = name.split("_", 1)[0]
                    for d, it in assets.items():
                        if d.startswith(prefix) or (it.get("path") == str(p)):
                            digest = d
                            break
                    if not digest:
                        for d in mirror:
                            if d.startswith(prefix):
                                digest = d
                                break
                if not digest:
                    digest = digest_for_path(p)
                st = p.stat()
                prev = assets.get(digest)
                if prev and prev.get("path") == str(p) and prev.get("mtime") == st.st_mtime:
                    continue
                try:
                    rel = str(p.relative_to(root))
                except Exception:
                    rel = name
                assets[digest] = {
                    **(prev or {}),
                    "digest": digest,
                    "path": str(p),
                    "rel": rel,
                    "name": name,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "media_type": _media_type(p),
                    "updated_at": time.time(),
                }
                added += 1
            except OSError:
                continue
        if limit is not None and count_walk > limit:
            break

    if enrich:
        for digest, rec in list(assets.items()):
            if get_tags(digest):
                continue
            p = Path(rec.get("path") or "")
            if not p.is_file():
                continue
            if rec.get("media_type") != "image":
                continue
            try:
                enrich_and_store(p, digest=digest, filename=rec.get("name") or p.name, run_vision=False)
                enriched += 1
            except Exception:
                pass

    cat["assets"] = assets
    _save_catalog(cat)
    return {
        "ok": True,
        "root": str(root),
        "count": len(assets),
        "added": added,
        "updated": updated,
        "enriched": enriched,
    }


def _media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".mov", ".mp4", ".m4v", ".3gp", ".avi"}:
        return "video"
    return "image"


def ensure_thumb(digest: str, path: Path, *, max_edge: int = 360) -> Path | None:
    dest = thumbs_root() / f"{digest[:24]}_{max_edge}.jpg"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Video preview frame via ffmpeg when available
    if path.suffix.lower() in {".mov", ".mp4", ".m4v", ".3gp", ".avi"}:
        try:
            import subprocess
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            cp = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    "0.5",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "4",
                    tmp_path,
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
            if cp.returncode == 0 and Path(tmp_path).is_file() and Path(tmp_path).stat().st_size > 32:
                try:
                    from PIL import Image

                    with Image.open(tmp_path) as im:
                        im = im.convert("RGB")
                        im.thumbnail((max_edge, max_edge))
                        im.save(dest, format="JPEG", quality=82, optimize=True)
                    Path(tmp_path).unlink(missing_ok=True)
                    return dest if dest.exists() else None
                except Exception:
                    # keep raw frame if PIL fails
                    Path(tmp_path).replace(dest)
                    return dest if dest.exists() else None
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return None
    try:
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((max_edge, max_edge))
            im.save(dest, format="JPEG", quality=82, optimize=True)
        return dest
    except Exception:
        return None


def list_assets(
    *,
    device_id: str = "",
    query: str = "",
    limit: int = 200,
    offset: int = 0,
    sort: str = "date_desc",
) -> dict[str, Any]:
    cat = _load_catalog()
    assets = list((cat.get("assets") or {}).values())
    if not assets:
        # auto-scan light
        scan_library(enrich=True, limit=500)
        cat = _load_catalog()
        assets = list((cat.get("assets") or {}).values())

    if device_id:
        assets = [a for a in assets if (a.get("device_id") or "") == device_id or device_id in (a.get("rel") or "")]

    if query:
        digests = set(search_by_query(query, limit=1000))
        q = query.lower()
        assets = [
            a
            for a in assets
            if a.get("digest") in digests
            or q in (a.get("name") or "").lower()
            or q in (a.get("rel") or "").lower()
        ]

    def sort_key(a: dict) -> float:
        tags = get_tags(a.get("digest") or "") or {}
        ts = tags.get("captured_at") or a.get("mtime") or a.get("updated_at") or 0
        return float(ts or 0)

    reverse = sort != "date_asc"
    assets.sort(key=sort_key, reverse=reverse)
    total = len(assets)
    page = assets[offset : offset + limit]
    items = [_public_asset(a) for a in page]
    return {"ok": True, "total": total, "offset": offset, "limit": limit, "items": items}


def _public_asset(a: dict[str, Any]) -> dict[str, Any]:
    digest = a.get("digest") or ""
    tags = get_tags(digest) or {}
    loc = tags.get("location") or {}
    return {
        "digest": digest,
        "name": a.get("name"),
        "rel": a.get("rel"),
        "device_id": a.get("device_id"),
        "size": a.get("size"),
        "media_type": a.get("media_type") or "image",
        "captured_at": tags.get("captured_at"),
        "captured_at_iso": tags.get("captured_at_iso"),
        "place_name": loc.get("place_name") or loc.get("city"),
        "setting": tags.get("setting"),
        "context": tags.get("context"),
        "keywords": (tags.get("keywords") or [])[:24],
        "people": tags.get("people") or [],
        "plants": tags.get("plants") or [],
        "objects": tags.get("objects") or [],
        "thumb_url": f"/photos/thumb/{digest}",
        "media_url": f"/photos/media/{digest}",
        "tags_url": f"/photos/tags/{digest}",
        "dual_ok": bool(a.get("hdd_ok") and a.get("nextcloud_ok")),
    }


def get_asset(digest: str) -> dict[str, Any] | None:
    cat = _load_catalog()
    a = (cat.get("assets") or {}).get(digest)
    if not a:
        # try rescan
        scan_library(enrich=False, limit=2000)
        a = (_load_catalog().get("assets") or {}).get(digest)
    return a


def albums_by_day(*, limit_days: int = 90) -> list[dict[str, Any]]:
    """Photos.app-style Moments / Days grouping."""
    res = list_assets(limit=5000, sort="date_desc")
    groups: dict[str, list] = defaultdict(list)
    for it in res["items"]:
        iso = it.get("captured_at_iso") or ""
        day = iso[:10] if iso else "Unknown"
        groups[day].append(it)
    days = []
    for day in sorted(groups.keys(), reverse=True)[:limit_days]:
        items = groups[day]
        places = [i.get("place_name") for i in items if i.get("place_name")]
        place = places[0] if places else None
        days.append(
            {
                "id": day,
                "title": _pretty_day(day),
                "subtitle": place,
                "count": len(items),
                "cover_digest": items[0]["digest"] if items else None,
                "items": items,
            }
        )
    return days


def _pretty_day(day: str) -> str:
    if day == "Unknown":
        return "Unknown date"
    try:
        t = time.strptime(day, "%Y-%m-%d")
        return time.strftime("%A, %B %-d, %Y", t) if os.name != "nt" else time.strftime("%A, %B %d, %Y", t)
    except Exception:
        return day


def albums_summary() -> list[dict[str, Any]]:
    """Albums strip: Recents, Videos, People, Places, Screenshots, dual-mirrored."""
    res = list_assets(limit=5000)
    items = res["items"]
    videos = [i for i in items if i.get("media_type") == "video"]
    places = [i for i in items if i.get("place_name")]
    people = [i for i in items if i.get("people")]
    dual = [i for i in items if i.get("dual_ok")]
    screenshots = [i for i in items if "screenshot" in " ".join(i.get("keywords") or [])]
    return [
        {"id": "recents", "title": "Recents", "count": len(items), "system": True},
        {"id": "videos", "title": "Videos", "count": len(videos), "system": True},
        {"id": "people", "title": "People", "count": len(people), "system": True},
        {"id": "places", "title": "Places", "count": len(places), "system": True},
        {"id": "screenshots", "title": "Screenshots", "count": len(screenshots), "system": True},
        {"id": "dual_mirror", "title": "Backed up (dual)", "count": len(dual), "system": True},
    ]


def resolve_media_path(digest: str) -> Path | None:
    a = get_asset(digest)
    if not a:
        return None
    p = Path(a.get("path") or "")
    return p if p.is_file() else None


def thumb_bytes(digest: str) -> bytes | None:
    a = get_asset(digest)
    if not a:
        return None
    p = Path(a.get("path") or "")
    if not p.is_file():
        return None
    th = ensure_thumb(digest, p)
    if th and th.is_file():
        return th.read_bytes()
    # fallback full read small (images only)
    if p.suffix.lower() in {".mov", ".mp4", ".m4v", ".3gp", ".avi"}:
        return None
    try:
        from PIL import Image

        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((360, 360))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=80)
            return buf.getvalue()
    except Exception:
        return None


def preview_kind(digest: str) -> str:
    """image | video | unknown"""
    a = get_asset(digest) or {}
    mt = (a.get("media_type") or "").lower()
    if mt == "video":
        return "video"
    name = (a.get("name") or a.get("path") or "").lower()
    if name.endswith((".mov", ".mp4", ".m4v", ".3gp", ".avi")):
        return "video"
    return "image" if name else "unknown"


def re_enrich_digest(digest: str, *, run_vision: bool = True) -> dict[str, Any]:
    a = get_asset(digest)
    if not a:
        return {"ok": False, "error": "not_found"}
    p = Path(a.get("path") or "")
    if not p.is_file():
        return {"ok": False, "error": "missing_file"}
    rec = enrich_and_store(p, digest=digest, filename=a.get("name") or p.name, run_vision=run_vision)
    return {"ok": True, "tags": rec}


def display_policy() -> dict[str, Any]:
    return {
        "apple_photos_app": {
            "can_show_mac_hdd_as_placeholders": False,
            "reason": (
                "Apple does not allow third-party apps to inject Mac/HDD backup "
                "originals into the system Photos app as iCloud-style placeholders."
            ),
        },
        "strategy": "cumulous_photos_clone",
        "preferred_viewer": "Cumulous Photos (in-app, Photos.app-like)",
        "also_available": "Nextcloud app streaming from this Mac",
        "sync": "Persistently updated from dual-mirror backup; viewable on all devices via Cumulous API",
        "tagging_upgrade": (
            "Richer than Photos: capture date/location, reverse place, people/plants/objects, "
            "setting, scene context, activities, colors, free-text relatable details + search"
        ),
    }
