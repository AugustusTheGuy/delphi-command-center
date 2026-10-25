"""Music + Podcast dual-mirror vault and gated free-space.

CEO locks:
  - Dual-backup all Music for later restore (HDD + Nextcloud).
  - Apple Music subscription active → cloud-eligible offline packs re-downloadable.
  - Free: Cache, Cache_LoFi, cloud-eligible Downloads, podcast media only.
  - Never delete local-only tracks.
  - Leave playlists in Music **untouched** (never free, never modify on device).
  - Never free /DCIM or /PhotoData.
  - Free only after dual-mirror verify of each freeable item.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from cumulous.paths import EXTERNALSSD_ROOT, ensure_internal, externalssd_mounted

AUDIO_EXT = {
    ".m4a",
    ".mp3",
    ".aac",
    ".alac",
    ".wav",
    ".aiff",
    ".aif",
    ".flac",
    ".caf",
    ".m4p",
    ".m4b",
    ".ogg",
    ".wma",
}

PLAYLIST_EXT = {".m3u", ".m3u8", ".pls", ".xml", ".plist"}

METADATA_EXT = {".plist", ".xml", ".itdb", ".itl", ".db", ".json", ".strings"}

# AFC roots we walk (never DCIM/PhotoData)
MUSIC_ROOTS = [
    "/Music",
    "/iTunes_Control/Music",
    "/iTunes_Control/iTunes",
]
PODCAST_ROOTS = [
    "/Podcasts",
]

# Paths that must never be removed or rewritten on the device
PROTECTED_PREFIXES = (
    "/DCIM",
    "/PhotoData",
)

# Playlist-related path fragments (leave on device untouched)
PLAYLIST_PATH_MARKERS = (
    "playlist",
    "playlists",
    "genius",
    "smart playlist",
    "purchases.plist",  # keep library meta conservative
)


def music_library_root() -> Path:
    if externalssd_mounted() and not os.environ.get("CUMULOUS_FORCE_INTERNAL_VAULT"):
        d = EXTERNALSSD_ROOT / "CumulousMusic"
    else:
        d = Path.home() / "CumulousMusic"
    d.mkdir(parents=True, exist_ok=True)
    return d


def podcast_library_root() -> Path:
    if externalssd_mounted() and not os.environ.get("CUMULOUS_FORCE_INTERNAL_VAULT"):
        d = EXTERNALSSD_ROOT / "CumulousPodcasts"
    else:
        d = Path.home() / "CumulousPodcasts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prefs_path() -> Path:
    return ensure_internal() / "music_offload.json"


def mirror_index_path() -> Path:
    return ensure_internal() / "music_mirror_index.json"


def harvest_state_path() -> Path:
    return ensure_internal() / "music_harvest_state.json"


def recent_podcast_names_path() -> Path:
    return ensure_internal() / "recent_podcast_names.json"


def free_log_path() -> Path:
    return ensure_internal() / "music_free_log.json"


def default_prefs() -> dict[str, Any]:
    return {
        "backup_music": True,
        "backup_app_data": True,
        "backup_podcasts": True,
        "host_on_hdd": True,
        "host_on_nextcloud": True,
        "require_dual_mirror_before_delete": True,
        "never_delete_local_only_tracks": True,
        "leave_playlists_untouched": True,  # hard lock
        "music_free_allowlist": ["cache", "cloud_eligible"],
        "podcast_free_media": True,
        "podcast_keep_recent_names_only": True,
        "podcast_recent_names_limit": 50,
        "apple_music_subscription_active": True,
        "notes": (
            "Dual-mirror Music + Podcasts to HDD + Nextcloud. "
            "Free Cache + cloud-eligible Downloads + podcast media after dual-verify. "
            "Local-only tracks stay on phone. Playlists left untouched on device. "
            "Never free DCIM/PhotoData."
        ),
    }


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    ensure_internal()
    path.write_text(json.dumps(data, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_prefs() -> dict[str, Any]:
    p = prefs_path()
    if not p.exists():
        prefs = default_prefs()
        save_prefs(prefs)
        return prefs
    try:
        data = json.loads(p.read_text())
        base = default_prefs()
        base.update(data)
        # hard locks cannot be disabled via partial prefs
        base["never_delete_local_only_tracks"] = True
        base["leave_playlists_untouched"] = True
        return base
    except Exception:
        return default_prefs()


def save_prefs(prefs: dict[str, Any]) -> None:
    prefs = {**prefs}
    prefs["never_delete_local_only_tracks"] = True
    prefs["leave_playlists_untouched"] = True
    prefs["updated_at"] = time.time()
    _save_json(prefs_path(), prefs)


def enable_always_music_and_app_data() -> dict[str, Any]:
    prefs = load_prefs()
    prefs["backup_music"] = True
    prefs["backup_app_data"] = True
    prefs["backup_podcasts"] = True
    save_prefs(prefs)
    return prefs


def load_mirror_index() -> dict:
    return _load_json(mirror_index_path(), {"items": {}})


def save_mirror_index(data: dict) -> None:
    data["updated_at"] = time.time()
    _save_json(mirror_index_path(), data)


def load_harvest_state() -> dict[str, Any]:
    return _load_json(harvest_state_path(), {"status": "idle"})


def save_harvest_state(state: dict[str, Any]) -> None:
    state = {**state, "updated_at": time.time()}
    _save_json(harvest_state_path(), state)


def load_recent_podcast_names() -> dict[str, Any]:
    return _load_json(recent_podcast_names_path(), {"names": [], "updated_at": 0})


def save_recent_podcast_names(names: list[str], *, limit: int | None = None) -> dict[str, Any]:
    prefs = load_prefs()
    lim = int(limit if limit is not None else prefs.get("podcast_recent_names_limit") or 50)
    cleaned: list[str] = []
    seen: set[str] = set()
    for n in names:
        s = str(n or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
        if len(cleaned) >= lim:
            break
    data = {"names": cleaned, "updated_at": time.time(), "limit": lim}
    _save_json(recent_podcast_names_path(), data)
    return data


def classify_music_path(afc_path: str) -> str:
    """Return class for an AFC path.

    Classes:
      cache | cloud_eligible | local_only | playlist | metadata | podcast_media | other

    Playlists are never freeable. Uncertain audio → local_only.
    """
    path = (afc_path or "").replace("\\", "/")
    low = path.lower()
    name = Path(path).name
    ext = Path(name).suffix.lower()

    if any(low.startswith(p.lower()) for p in PROTECTED_PREFIXES):
        return "other"

    # Playlists — leave untouched (never free)
    if ext in PLAYLIST_EXT or any(m in low for m in PLAYLIST_PATH_MARKERS):
        if ext in PLAYLIST_EXT or "playlist" in low:
            return "playlist"

    # Podcast media
    if low.startswith("/podcasts") or "/podcasts/" in low:
        if ext in AUDIO_EXT or ext in {".mp4", ".m4v", ".mov"}:
            return "podcast_media"
        if ext in METADATA_EXT:
            return "metadata"
        # unknown under Podcasts → treat as freeable media only if looks like content file
        if ext and ext not in {".plist", ".xml", ".db"}:
            return "podcast_media"
        return "metadata"

    # Cache (freeable after dual)
    if "/music/cache" in low or low.startswith("/music/cache"):
        return "cache"
    if "cache_lofi" in low or "/cache_lofi" in low:
        return "cache"
    if "/music/" in low and "/cache" in low:
        return "cache"

    # iTunes_Control playlists / library meta
    if "itunes_control" in low:
        if "playlist" in low or ext in PLAYLIST_EXT:
            return "playlist"
        if ext in METADATA_EXT or ext in {".itdb", ".itl"}:
            return "metadata"
        if ext in AUDIO_EXT:
            # Music under iTunes_Control often is library content — conservative local_only
            # unless clearly a cache path
            if "cache" in low:
                return "cache"
            return "local_only"

    # Downloads: with Apple Music sub, default cloud_eligible for audio under Downloads;
    # files that look purchased/local stay local_only.
    if "/music/downloads" in low or low.startswith("/music/downloads"):
        if ext in AUDIO_EXT or not ext:
            # Heuristic: Apple Music offline packs often use opaque hashed names or .m4p
            # Purchased iTunes often .m4a with human names — still cloud-re-gettable if AM/purchase.
            # CEO: local-only must stay. Prefer cloud_eligible for Downloads when AM active
            # UNLESS name strongly suggests user-ripped (e.g. .wav/.flac/.aiff without DRM).
            prefs = load_prefs()
            if prefs.get("apple_music_subscription_active", True):
                if ext in {".wav", ".flac", ".aiff", ".aif"}:
                    return "local_only"
                if ext == ".m4p":  # protected Apple
                    return "cloud_eligible"
                # Standard offline AM packs
                return "cloud_eligible"
            return "local_only"
        if ext in PLAYLIST_EXT:
            return "playlist"
        return "metadata"

    # Other /Music audio → local_only (safe)
    if low.startswith("/music/") or "/music/" in low:
        if ext in AUDIO_EXT:
            return "local_only"
        if ext in PLAYLIST_EXT or "playlist" in low:
            return "playlist"
        if ext in METADATA_EXT:
            return "metadata"
        return "local_only"

    if ext in AUDIO_EXT:
        return "local_only"
    if ext in PLAYLIST_EXT:
        return "playlist"
    return "other"


def is_freeable_class(cls: str, prefs: dict[str, Any] | None = None) -> bool:
    prefs = prefs or load_prefs()
    if prefs.get("leave_playlists_untouched", True) and cls == "playlist":
        return False
    if prefs.get("never_delete_local_only_tracks", True) and cls == "local_only":
        return False
    if cls in ("metadata", "other", "playlist"):
        return False
    allow = list(prefs.get("music_free_allowlist") or ["cache", "cloud_eligible"])
    if cls == "podcast_media":
        return bool(prefs.get("podcast_free_media", True))
    return cls in allow


def _kind_for_class(cls: str) -> str:
    if cls == "podcast_media":
        return "podcast"
    if cls == "playlist":
        return "playlist"
    return "music"


def _vault_root_for(kind: str) -> Path:
    if kind == "podcast":
        return podcast_library_root()
    return music_library_root()


def _device_album_dir(kind: str, device_id: str, apple_account_id: str = "") -> Path:
    root = _vault_root_for(kind)
    safe_dev = "".join(c if c.isalnum() or c in "-_" else "_" for c in device_id)[:80]
    safe_acct = "".join(
        c if c.isalnum() or c in "-_@." else "_" for c in (apple_account_id or "shared")
    )[:80]
    d = root / safe_acct / safe_dev
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_on_hdd(
    data: bytes,
    *,
    device_id: str,
    rel_name: str,
    apple_account_id: str = "",
    kind: str = "music",
    afc_path: str = "",
) -> dict[str, Any]:
    album = _device_album_dir(kind, device_id, apple_account_id)
    safe_name = Path(rel_name.replace("\\", "/")).name or f"audio_{int(time.time())}"
    digest = hashlib.sha256(data).hexdigest()
    # Preserve a hint of AFC relative structure in filename when useful
    dest = album / f"{digest[:12]}_{safe_name}"
    if not dest.exists():
        dest.write_bytes(data)
    return {
        "ok": True,
        "path": str(dest),
        "digest": digest,
        "size": len(data),
        "afc_path": afc_path,
        "kind": kind,
    }


def dual_mirror_music_bytes(
    data: bytes,
    *,
    device_id: str,
    rel_name: str,
    apple_account_id: str = "",
    afc_path: str = "",
    cls: str | None = None,
) -> dict[str, Any]:
    """Write music/podcast bytes to HDD + Nextcloud; index with class. Never queues playlist free."""
    prefs = load_prefs()
    path = afc_path or rel_name
    item_class = cls or classify_music_path(path)
    kind = _kind_for_class(item_class)

    hdd = store_on_hdd(
        data,
        device_id=device_id,
        rel_name=rel_name,
        apple_account_id=apple_account_id,
        kind=kind,
        afc_path=path,
    )
    digest = hdd["digest"]
    remote_rel = (
        f"cumulous_{kind}/{apple_account_id or 'shared'}/{device_id}/"
        f"{digest[:12]}_{Path(rel_name).name}"
    )

    nc_ok = False
    nc_result: dict[str, Any] = {"ok": False, "skipped": True}
    if prefs.get("host_on_nextcloud", True):
        try:
            from cumulous.nextcloud_client import nextcloud_reachable, upload_bytes

            reach = nextcloud_reachable()
            if reach.get("ok"):
                nc_result = upload_bytes(remote_rel, data)
                nc_ok = bool(nc_result.get("ok"))
            else:
                nc_result = {"ok": False, "error": reach.get("error") or "nextcloud_unreachable"}
        except Exception as e:
            nc_result = {"ok": False, "error": str(e)[:200]}

    hdd_ok = bool(hdd.get("ok"))
    dual_ok = hdd_ok and nc_ok
    freeable = is_freeable_class(item_class, prefs)
    # Playlists and local_only never safe_to_delete
    safe_delete = False
    if freeable and prefs.get("require_dual_mirror_before_delete", True):
        safe_delete = dual_ok
    elif freeable:
        safe_delete = hdd_ok

    idx = load_mirror_index()
    items = idx.setdefault("items", {})
    prev = dict(items.get(digest) or {})
    merged_nc = bool(nc_ok or prev.get("nextcloud_ok"))
    items[digest] = {
        **prev,
        "digest": digest,
        "device_id": device_id or prev.get("device_id") or "",
        "apple_account_id": apple_account_id or prev.get("apple_account_id") or "",
        "name": Path(rel_name).name or prev.get("name") or "",
        "size": len(data) or prev.get("size") or 0,
        "hdd_ok": bool(hdd_ok or prev.get("hdd_ok")),
        "hdd_path": hdd.get("path") or prev.get("hdd_path"),
        "nextcloud_ok": merged_nc,
        "nextcloud_rel": (remote_rel if nc_ok else "") or prev.get("nextcloud_rel") or "",
        "afc_path": path or prev.get("afc_path") or "",
        "class": item_class,
        "kind": kind,
        "safe_to_delete_on_device": bool(safe_delete) and not prev.get("deleted_on_device"),
        "playlist_untouched": item_class == "playlist",
        "updated_at": time.time(),
    }
    dual_ok = bool(items[digest]["hdd_ok"] and items[digest]["nextcloud_ok"])
    if freeable and prefs.get("require_dual_mirror_before_delete", True):
        items[digest]["safe_to_delete_on_device"] = dual_ok and not prev.get("deleted_on_device")
    elif freeable:
        items[digest]["safe_to_delete_on_device"] = bool(items[digest]["hdd_ok"]) and not prev.get(
            "deleted_on_device"
        )
    else:
        items[digest]["safe_to_delete_on_device"] = False

    save_mirror_index(idx)
    return {
        "ok": hdd_ok,
        "dual_ok": dual_ok,
        "digest": digest,
        "class": item_class,
        "kind": kind,
        "safe_to_delete_on_device": items[digest]["safe_to_delete_on_device"],
        "hdd": hdd,
        "nextcloud": nc_result,
        "size": len(data),
    }


def library_status() -> dict[str, Any]:
    idx = load_mirror_index()
    items = list((idx.get("items") or {}).values())
    by_class: dict[str, dict[str, int]] = {}
    for it in items:
        c = str(it.get("class") or "other")
        bucket = by_class.setdefault(c, {"count": 0, "bytes": 0, "dual_ok": 0, "freeable": 0})
        bucket["count"] += 1
        bucket["bytes"] += int(it.get("size") or 0)
        if it.get("hdd_ok") and it.get("nextcloud_ok"):
            bucket["dual_ok"] += 1
        if it.get("safe_to_delete_on_device"):
            bucket["freeable"] += 1
    dual = sum(1 for it in items if it.get("hdd_ok") and it.get("nextcloud_ok"))
    freeable_bytes = sum(
        int(it.get("size") or 0) for it in items if it.get("safe_to_delete_on_device")
    )
    prefs = load_prefs()
    return {
        "music_root": str(music_library_root()),
        "podcast_root": str(podcast_library_root()),
        "indexed_count": len(items),
        "mirrored_dual_count": dual,
        "by_class": by_class,
        "freeable_bytes_projected": freeable_bytes,
        "prefs": prefs,
        "recent_podcast_names": load_recent_podcast_names(),
        "playlists_untouched": True,
        "local_only_protected": True,
    }


def freeable_music_items() -> list[dict[str, Any]]:
    """Items safe to free: dual-ok + freeable class; never playlist/local_only."""
    prefs = load_prefs()
    out: list[dict[str, Any]] = []
    for dig, it in (load_mirror_index().get("items") or {}).items():
        cls = str(it.get("class") or "")
        if not is_freeable_class(cls, prefs):
            continue
        if not it.get("safe_to_delete_on_device"):
            continue
        if it.get("deleted_on_device"):
            continue
        if cls == "playlist" or it.get("playlist_untouched"):
            continue
        if cls == "local_only":
            continue
        out.append({"digest": dig, **it})
    return out


def _afc_remove_music_path(udid: str, remote_path: str, cls: str) -> dict[str, Any]:
    """AFC unlink only freeable Music/Podcast paths. Playlists and photos blocked."""
    if not udid or not remote_path or not str(remote_path).startswith("/"):
        return {"ok": False, "error": "invalid_path"}
    low = remote_path.replace("\\", "/").lower()
    if any(low.startswith(p.lower()) for p in PROTECTED_PREFIXES):
        return {"ok": False, "error": "photos_protected"}
    if classify_music_path(remote_path) == "playlist" or cls == "playlist":
        return {"ok": False, "error": "playlist_untouched"}
    if cls == "local_only" or classify_music_path(remote_path) == "local_only":
        return {"ok": False, "error": "local_only_protected"}
    allowed = (
        low.startswith("/music/")
        or low.startswith("/podcasts")
        or low.startswith("/itunes_control/")
    )
    if not allowed:
        return {"ok": False, "error": "path_not_allowed"}
    # Extra playlist path guard
    if "playlist" in low:
        return {"ok": False, "error": "playlist_untouched"}
    try:
        import asyncio

        async def _rm() -> dict[str, Any]:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.afc import AfcService

            ld = await create_using_usbmux(serial=udid)
            async with AfcService(ld) as afc:
                await afc.rm(remote_path)
            return {"ok": True, "removed": remote_path}

        return asyncio.run(_rm())
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "path": remote_path}


def free_music_on_device_usb(
    *,
    udid: str = "",
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Remove dual-verified freeable Music/Podcast media from phone. Never playlists/local-only.

    Uses one AFC session with reconnects. Local-only + playlists always refused.
    """
    import asyncio

    from cumulous.photo_offload import usb_device_present

    prefs = load_prefs()
    assert prefs.get("leave_playlists_untouched", True)
    assert prefs.get("never_delete_local_only_tracks", True)

    usb = usb_device_present()
    udid = udid or str(usb.get("udid") or "")
    if not dry_run and not udid:
        return {
            "ok": False,
            "error": "usb_required",
            "message": "Plug in the iPhone with a USB cable to free Music/Podcast space.",
            "playlists_untouched": True,
            "local_only_protected": True,
        }

    items = freeable_music_items()
    if limit is not None:
        items = items[: int(limit)]

    removed = 0
    errors = 0
    skipped = 0
    bytes_removed = 0
    details: list[dict[str, Any]] = []
    idx = load_mirror_index()
    store = idx.setdefault("items", {})

    # Build safe worklist (hard skip local_only + playlist)
    work: list[dict[str, Any]] = []
    for it in items:
        dig = it.get("digest") or ""
        cls = str(it.get("class") or "")
        remote = str(it.get("afc_path") or "")
        if cls in ("playlist", "local_only", "metadata"):
            skipped += 1
            continue
        if not is_freeable_class(cls, prefs):
            skipped += 1
            continue
        if not remote.startswith("/"):
            errors += 1
            details.append({"digest": dig, "error": "no_afc_path"})
            continue
        if "playlist" in remote.lower():
            skipped += 1
            continue
        work.append(it)

    if dry_run:
        for it in work:
            removed += 1
            bytes_removed += int(it.get("size") or 0)
            details.append(
                {
                    "digest": it.get("digest"),
                    "would_remove": it.get("afc_path"),
                    "class": it.get("class"),
                }
            )
        log = {
            "ok": True,
            "dry_run": True,
            "removed": removed,
            "errors": 0,
            "skipped": skipped,
            "bytes_removed": bytes_removed,
            "playlists_untouched": True,
            "local_only_protected": True,
            "candidate_count": len(items),
            "details_sample": details[:40],
            "finished_at": time.time(),
        }
        _save_json(free_log_path(), log)
        return log

    async def _batch_rm() -> None:
        nonlocal removed, errors, bytes_removed, skipped
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService

        async def _open():
            ld = await create_using_usbmux(serial=udid)
            return AfcService(ld)

        afc_cm = await _open()
        afc = await afc_cm.__aenter__()
        try:
            for n, it in enumerate(work):
                dig = it.get("digest") or ""
                cls = str(it.get("class") or "")
                remote = str(it.get("afc_path") or "")
                # Belt-and-suspenders
                if cls in ("local_only", "playlist") or classify_music_path(remote) in (
                    "local_only",
                    "playlist",
                ):
                    skipped += 1
                    continue
                try:
                    await afc.rm(remote)
                    removed += 1
                    bytes_removed += int(it.get("size") or 0)
                    if dig in store:
                        store[dig]["deleted_on_device"] = True
                        store[dig]["safe_to_delete_on_device"] = False
                        store[dig]["deleted_at"] = time.time()
                    details.append({"digest": dig, "removed": remote, "class": cls})
                except Exception as e:
                    err = str(e)[:120]
                    # Already gone → count as success for free goal
                    if any(x in err.lower() for x in ("not found", "no such", "object not found", "eof")):
                        removed += 1
                        if dig in store:
                            store[dig]["deleted_on_device"] = True
                            store[dig]["safe_to_delete_on_device"] = False
                            store[dig]["deleted_at"] = time.time()
                        details.append({"digest": dig, "already_gone": remote, "class": cls})
                    else:
                        errors += 1
                        details.append({"digest": dig, "error": err, "path": remote})
                        # reconnect every few failures
                        if errors % 5 == 0:
                            try:
                                await afc_cm.__aexit__(None, None, None)
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
                            afc_cm = await _open()
                            afc = await afc_cm.__aenter__()
                if n % 25 == 0:
                    save_mirror_index(idx)
        finally:
            try:
                await afc_cm.__aexit__(None, None, None)
            except Exception:
                pass

    try:
        asyncio.run(_batch_rm())
    except Exception as e:
        errors += 1
        details.append({"error": f"session:{e}"[:160]})

    save_mirror_index(idx)

    log = {
        "ok": errors == 0 or removed > 0,
        "dry_run": False,
        "removed": removed,
        "errors": errors,
        "skipped": skipped,
        "bytes_removed": bytes_removed,
        "playlists_untouched": True,
        "local_only_protected": True,
        "candidate_count": len(items),
        "details_sample": details[:40],
        "finished_at": time.time(),
    }
    _save_json(free_log_path(), log)
    return log


def device_free_bytes(udid: str = "") -> dict[str, Any]:
    """Read free user-data bytes from connected device (AmountDataAvailable)."""
    try:
        import subprocess

        from cumulous.photo_offload import usb_device_present

        usb = usb_device_present()
        udid = udid or str(usb.get("udid") or "")
        if not udid:
            return {"ok": False, "error": "no_usb", "free_bytes": None}
        # Prefer disk_usage domain — AmountDataAvailable is true free space
        free_b: int | None = None
        capacity: int | None = None
        cp = subprocess.run(
            ["ideviceinfo", "-u", udid, "-q", "com.apple.disk_usage"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        for line in (cp.stdout or "").splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "AmountDataAvailable" and v.isdigit():
                free_b = int(v)
            if k == "TotalDataCapacity" and v.isdigit():
                capacity = int(v)
        if free_b is None:
            cp2 = subprocess.run(
                ["ideviceinfo", "-u", udid, "-k", "AmountDataAvailable"],
                capture_output=True,
                text=True,
                timeout=12,
            )
            v2 = (cp2.stdout or "").strip()
            if v2.isdigit():
                free_b = int(v2)
        return {
            "ok": free_b is not None,
            "free_bytes": free_b,
            "free_gb": round(free_b / 1e9, 2) if free_b is not None else None,
            "capacity_bytes": capacity,
            "udid": udid,
            "meets_16gb": bool(free_b is not None and free_b >= 16_000_000_000),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "free_bytes": None}


def _is_harvest_candidate(name: str, remote: str) -> bool:
    """True if path should be dual-mirrored (audio, playlist meta, podcast, caches)."""
    ext = Path(name).suffix.lower()
    cls = classify_music_path(remote)
    if cls in ("cache", "cloud_eligible", "local_only", "podcast_media", "playlist", "metadata"):
        return True
    if ext in AUDIO_EXT or ext in PLAYLIST_EXT:
        return True
    return False


def harvest_music_afc(
    *,
    device_id: str = "",
    udid: str = "",
    apple_account_id: str = "",
    limit: int | None = None,
    skip_existing: bool = True,
    include_podcasts: bool = True,
) -> dict[str, Any]:
    """Pull Music (+ Podcasts) via AFC and dual-mirror. Read-only for playlists (no free).

    Retries AFC reads, reconnects periodically, skips already-indexed AFC paths.
    Never frees local-only tracks or playlists (vault only).
    """
    import asyncio

    prefs = load_prefs()
    # Downloads first (bulk freeable with Apple Music), then rest
    roots = ["/Music/Downloads", "/Music/Cache", "/Music/Cache_LoFi"]
    roots.extend([r for r in MUSIC_ROOTS if r not in roots])
    if include_podcasts and prefs.get("backup_podcasts", True):
        roots.extend(PODCAST_ROOTS)

    state: dict[str, Any] = {
        "status": "running",
        "started_at": time.time(),
        "device_id": device_id,
        "udid": udid,
        "mirrored": 0,
        "dual_ok": 0,
        "skipped_existing": 0,
        "errors": 0,
        "scanned": 0,
        "bytes": 0,
        "by_class": {},
        "last_path": "",
        "current_root": "",
        "playlists_mirrored": 0,
        "playlists_untouched_on_device": True,
        "local_only_protected": True,
        "last_error": "",
        "reconnects": 0,
    }
    save_harvest_state(state)

    idx = load_mirror_index()
    items = idx.get("items") or {}
    known = set(items.keys())
    known_paths = {
        str(it.get("afc_path") or "")
        for it in items.values()
        if it.get("hdd_ok") and it.get("afc_path")
    }
    podcast_name_hits: list[tuple[float, str]] = []
    failed_paths: list[str] = []

    def _bump_class(cls: str, nbytes: int = 0) -> None:
        b = state["by_class"].setdefault(cls, {"count": 0, "bytes": 0})
        b["count"] += 1
        b["bytes"] += nbytes

    async def _read_with_retry(afc, remote: str, retries: int = 3) -> bytes | None:
        last_err = ""
        for attempt in range(retries):
            try:
                data = await afc.get_file_contents(remote)
                if data and len(data) >= 8:
                    return data
                last_err = "empty_or_tiny"
            except Exception as e:
                last_err = f"{type(e).__name__}:{str(e)[:120]}"
                await asyncio.sleep(0.4 * (attempt + 1))
        state["last_error"] = last_err
        return None

    async def _process_file(afc, remote: str, did: str) -> None:
        state["scanned"] = int(state.get("scanned") or 0) + 1
        state["last_path"] = remote
        name = Path(remote).name
        if not _is_harvest_candidate(name, remote):
            return
        cls = classify_music_path(remote)
        # Resume: skip by AFC path if already on HDD (do not re-pull; never free local_only/playlists here)
        if skip_existing and remote in known_paths:
            state["skipped_existing"] = int(state["skipped_existing"]) + 1
            return
        data = await _read_with_retry(afc, remote)
        if data is None:
            state["errors"] = int(state["errors"]) + 1
            failed_paths.append(remote)
            return
        digest = hashlib.sha256(data).hexdigest()
        if skip_existing and digest in known:
            state["skipped_existing"] = int(state["skipped_existing"]) + 1
            known_paths.add(remote)
            _bump_class(cls, 0)
            return
        try:
            res = dual_mirror_music_bytes(
                data,
                device_id=did,
                rel_name=name,
                apple_account_id=apple_account_id,
                afc_path=remote,
                cls=cls,
            )
            if res.get("ok"):
                state["mirrored"] = int(state["mirrored"]) + 1
                known.add(digest)
                known_paths.add(remote)
                state["bytes"] = int(state["bytes"]) + len(data)
                _bump_class(cls, len(data))
                if cls == "playlist":
                    state["playlists_mirrored"] = int(state["playlists_mirrored"]) + 1
            if res.get("dual_ok"):
                state["dual_ok"] = int(state["dual_ok"]) + 1
            elif not res.get("ok"):
                state["errors"] = int(state["errors"]) + 1
                failed_paths.append(remote)
            if cls == "podcast_media":
                parts = [p for p in remote.split("/") if p and p not in ("Podcasts",)]
                label = " / ".join(parts[-2:]) if parts else name
                podcast_name_hits.append((time.time(), label))
        except Exception as e:
            state["errors"] = int(state["errors"]) + 1
            state["last_error"] = str(e)[:160]
            failed_paths.append(remote)

    async def _walk(afc, path: str, did: str, depth: int = 0) -> None:
        if limit is not None and int(state["mirrored"]) >= limit:
            return
        try:
            entries = await afc.listdir(path)
        except Exception as e:
            state["last_error"] = f"listdir:{path}:{e}"[:160]
            return
        for name in entries or []:
            if limit is not None and int(state["mirrored"]) >= limit:
                return
            if name in (".", ".."):
                continue
            child = f"{path.rstrip('/')}/{name}"
            ext = Path(name).suffix.lower()
            # Flat audio files under Downloads: never treat .m4p as directory
            if ext in AUDIO_EXT and path.rstrip("/").endswith("Downloads"):
                await _process_file(afc, child, did)
                if int(state["scanned"]) % 5 == 0:
                    save_harvest_state(state)
                continue
            if ext in AUDIO_EXT | PLAYLIST_EXT | METADATA_EXT | {".mp4", ".m4v", ".mov", ".db"}:
                try:
                    await afc.listdir(child)
                    if depth < 16:
                        await _walk(afc, child, did, depth + 1)
                    continue
                except Exception:
                    await _process_file(afc, child, did)
                    if int(state["scanned"]) % 5 == 0:
                        save_harvest_state(state)
                    continue
            try:
                await afc.listdir(child)
                is_dir = True
            except Exception:
                is_dir = False
            if is_dir and depth < 16:
                await _walk(afc, child, did, depth + 1)
            else:
                await _process_file(afc, child, did)
                if int(state["scanned"]) % 5 == 0:
                    save_harvest_state(state)

    async def _run() -> dict[str, Any]:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService

        kwargs: dict[str, Any] = {}
        if udid:
            kwargs["serial"] = udid
        did = device_id or udid or "device"

        async def _fresh_afc():
            ld = await create_using_usbmux(**kwargs)
            return AfcService(ld)

        async def _list_paths(root: str) -> list[str]:
            """Collect file paths under root with a short-lived AFC session."""
            out: list[str] = []
            cm = await _fresh_afc()
            afc = await cm.__aenter__()
            try:
                async def walk(path: str, depth: int = 0) -> None:
                    try:
                        entries = await afc.listdir(path)
                    except Exception:
                        return
                    for name in entries or []:
                        if name in (".", ".."):
                            continue
                        child = f"{path.rstrip('/')}/{name}"
                        ext = Path(name).suffix.lower()
                        if ext in AUDIO_EXT and path.rstrip("/").endswith("Downloads"):
                            out.append(child)
                            continue
                        if ext in AUDIO_EXT | PLAYLIST_EXT | METADATA_EXT | {
                            ".mp4",
                            ".m4v",
                            ".mov",
                            ".db",
                        }:
                            try:
                                await afc.listdir(child)
                                if depth < 16:
                                    await walk(child, depth + 1)
                            except Exception:
                                out.append(child)
                            continue
                        try:
                            await afc.listdir(child)
                            is_dir = True
                        except Exception:
                            is_dir = False
                        if is_dir and depth < 16:
                            await walk(child, depth + 1)
                        else:
                            out.append(child)

                await walk(root, 0)
            finally:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
            return out

        # Prefer enumerate-then-pull with reconnection every N files (AFC pipe is fragile)
        batch_reconnect = 15
        for root in roots:
            state["current_root"] = root
            save_harvest_state(state)
            try:
                paths = await _list_paths(root)
            except Exception as e:
                state["last_error"] = f"list:{root}:{e}"[:160]
                paths = []
            state["queued"] = len(paths)
            save_harvest_state(state)

            cm = await _fresh_afc()
            afc = await cm.__aenter__()
            n_in_session = 0
            try:
                for remote in paths:
                    if limit is not None and int(state["mirrored"]) >= limit:
                        break
                    if skip_existing and remote in known_paths:
                        state["skipped_existing"] = int(state["skipped_existing"]) + 1
                        continue
                    await _process_file(afc, remote, did)
                    n_in_session += 1
                    if int(state["scanned"]) % 5 == 0:
                        save_harvest_state(state)
                    if n_in_session >= batch_reconnect:
                        try:
                            await cm.__aexit__(None, None, None)
                        except Exception:
                            pass
                        await asyncio.sleep(0.25)
                        state["reconnects"] = int(state.get("reconnects") or 0) + 1
                        cm = await _fresh_afc()
                        afc = await cm.__aenter__()
                        n_in_session = 0
            finally:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass

        # Retry failed paths one-by-one with fresh sessions
        if failed_paths:
            retry = list(dict.fromkeys(failed_paths))  # unique preserve order
            failed_paths.clear()
            for remote in retry:
                if limit is not None and int(state["mirrored"]) >= limit:
                    break
                if skip_existing and remote in known_paths:
                    continue
                cm = await _fresh_afc()
                afc = await cm.__aenter__()
                try:
                    await _process_file(afc, remote, did)
                finally:
                    try:
                        await cm.__aexit__(None, None, None)
                    except Exception:
                        pass
                state["reconnects"] = int(state.get("reconnects") or 0) + 1
                if int(state["scanned"]) % 3 == 0:
                    save_harvest_state(state)
        return state

    try:
        st = asyncio.run(_run())
        st["status"] = "complete"
        st["finished_at"] = time.time()
        st["failed_remaining"] = len(failed_paths)
        if podcast_name_hits:
            podcast_name_hits.sort(key=lambda x: -x[0])
            names = [n for _, n in podcast_name_hits]
            save_recent_podcast_names(names)
            st["recent_podcast_names"] = load_recent_podcast_names()
        st["library"] = library_status()
        save_harvest_state(st)
        return {"ok": True, **st}
    except Exception as e:
        state["status"] = "error"
        state["error"] = str(e)[:240]
        state["finished_at"] = time.time()
        save_harvest_state(state)
        return {"ok": False, **state}


_music_harvest_thread: threading.Thread | None = None


def _music_harvest_pid_path() -> Path:
    return ensure_internal() / "music_harvest.pid"


def music_harvest_is_alive() -> bool:
    cur = load_harvest_state()
    if cur.get("status") != "running":
        return False
    pid_p = _music_harvest_pid_path()
    if pid_p.exists():
        try:
            pid = int(pid_p.read_text().strip())
            os.kill(pid, 0)
            return True
        except Exception:
            pass
    global _music_harvest_thread
    if _music_harvest_thread is not None and _music_harvest_thread.is_alive():
        return True
    try:
        age = time.time() - float(cur.get("updated_at") or 0)
        if age < 90:
            return True
    except Exception:
        pass
    return False


def start_music_harvest(
    *,
    device_id: str = "",
    udid: str = "",
    apple_account_id: str = "",
    limit: int | None = None,
    force: bool = False,
    use_process: bool = True,
) -> dict[str, Any]:
    """Background music+podcast harvest with keep-awake policy."""
    global _music_harvest_thread
    import subprocess
    import sys

    enable_always_music_and_app_data()
    cur = load_harvest_state()
    if not force and music_harvest_is_alive():
        try:
            from cumulous.device_power import begin_backup_wake_policy

            begin_backup_wake_policy(
                session_id=f"music_harvest_{device_id or udid or 'device'}",
                device_name="ROB IPHONE (2)",
            )
        except Exception:
            pass
        return {"ok": True, "already_running": True, "state": cur, "alive": True}

    save_harvest_state(
        {
            **cur,
            "status": "running",
            "started_at": time.time(),
            "device_id": device_id,
            "udid": udid,
            "mirrored": 0,
            "dual_ok": 0,
            "playlists_untouched_on_device": True,
        }
    )

    try:
        from cumulous.device_power import begin_backup_wake_policy

        begin_backup_wake_policy(
            session_id=f"music_harvest_{device_id or udid or 'device'}",
            device_name="ROB IPHONE (2)",
        )
    except Exception:
        pass

    if use_process:
        env = os.environ.copy()
        env["CUMULOUS_MUSIC_HARVEST_DEVICE_ID"] = device_id or ""
        env["CUMULOUS_MUSIC_HARVEST_UDID"] = udid or ""
        env["CUMULOUS_MUSIC_HARVEST_APPLE_ID"] = apple_account_id or ""
        if limit is not None:
            env["CUMULOUS_MUSIC_HARVEST_LIMIT"] = str(limit)
        log_path = ensure_internal() / "music_harvest_worker.log"
        try:
            log_f = open(log_path, "a")  # noqa: SIM115
            proc = subprocess.Popen(
                [sys.executable, "-m", "cumulous.music_harvest_worker"],
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            _music_harvest_pid_path().write_text(str(proc.pid))
            return {
                "ok": True,
                "started": True,
                "mode": "process",
                "pid": proc.pid,
                "log": str(log_path),
            }
        except Exception as e:
            save_harvest_state({**load_harvest_state(), "status": "error", "error": str(e)[:200]})
            return {"ok": False, "error": str(e)[:200]}

    def _run() -> None:
        try:
            harvest_music_afc(
                device_id=device_id,
                udid=udid,
                apple_account_id=apple_account_id,
                limit=limit,
            )
        finally:
            try:
                from cumulous.device_power import end_backup_wake_policy

                end_backup_wake_policy(reason="music_harvest_thread_exit")
            except Exception:
                pass

    _music_harvest_thread = threading.Thread(target=_run, daemon=True)
    _music_harvest_thread.start()
    return {"ok": True, "started": True, "mode": "thread"}


def music_harvest_progress() -> dict[str, Any]:
    st = load_harvest_state()
    return {
        "harvest": st,
        "alive": music_harvest_is_alive(),
        "library": library_status(),
        "device_free": device_free_bytes(),
    }


def backfill_nextcloud_dual(*, limit: int | None = None) -> dict[str, Any]:
    """Upload HDD music/podcast vault items that lack nextcloud_ok (add-only dual complete)."""
    from pathlib import Path

    from cumulous.nextcloud_client import nextcloud_reachable, upload_bytes

    reach = nextcloud_reachable()
    if not reach.get("ok"):
        return {"ok": False, "error": "nextcloud_unreachable", "detail": reach}

    idx = load_mirror_index()
    items = idx.setdefault("items", {})
    fixed = 0
    fail = 0
    skip = 0
    prefs = load_prefs()
    for dig, it in list(items.items()):
        if limit is not None and fixed >= int(limit):
            break
        if it.get("nextcloud_ok") and it.get("hdd_ok"):
            skip += 1
            continue
        hdd = it.get("hdd_path") or ""
        p = Path(hdd) if hdd else None
        if not p or not p.is_file():
            fail += 1
            continue
        try:
            data = p.read_bytes()
        except OSError:
            fail += 1
            continue
        kind = it.get("kind") or "music"
        aid = it.get("apple_account_id") or "shared"
        did = it.get("device_id") or "device"
        name = it.get("name") or p.name
        remote_rel = f"cumulous_{kind}/{aid}/{did}/{str(dig)[:12]}_{name}"
        res = upload_bytes(remote_rel, data)
        if res.get("ok"):
            cls = str(it.get("class") or "")
            it["nextcloud_ok"] = True
            it["nextcloud_rel"] = remote_rel
            dual = bool(it.get("hdd_ok"))
            freeable = is_freeable_class(cls, prefs)
            it["safe_to_delete_on_device"] = bool(
                freeable and dual and not it.get("deleted_on_device")
            )
            if cls == "playlist":
                it["safe_to_delete_on_device"] = False
                it["playlist_untouched"] = True
            items[dig] = it
            fixed += 1
            if fixed % 20 == 0:
                save_mirror_index(idx)
        else:
            fail += 1
    save_mirror_index(idx)
    return {
        "ok": True,
        "fixed": fixed,
        "fail": fail,
        "already_dual": skip,
        "library": library_status(),
    }


def restore_notes_for_ceo() -> str:
    lib = library_status()
    names = (lib.get("recent_podcast_names") or {}).get("names") or []
    return (
        "Cumulous Music restore\n"
        f"- HDD vault: {lib.get('music_root')}\n"
        f"- Podcast vault: {lib.get('podcast_root')}\n"
        f"- Dual-mirrored items: {lib.get('mirrored_dual_count')}\n"
        "- Apple Music: re-download cloud songs in the Music app (subscription active).\n"
        "- Local-only tracks: left on your phone; also in the Cumulous vault.\n"
        "- Playlists: left untouched on your phone (also copied to vault if found).\n"
        f"- Recent podcast names kept: {', '.join(names[:15]) or '(none yet)'}\n"
        "- iCloud 5 GB is not used as a music restore path.\n"
    )
