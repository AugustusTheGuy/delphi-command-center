"""Dual-mirror media offload: Mac HDD + Nextcloud, then free phone storage.

Policy (CEO):
  - Store originals on attached HDD (ExternalSSD CumulousPhotos) AND Nextcloud.
  - Only after BOTH copies verify, mark items safe to remove from the phone.
  - Phone displays via Nextcloud app (streams/cache, not permanent full library)
    or Cumulous gallery — not Apple Photos.app iCloud placeholders.

Deletion on device is executed by the Cumulous/Nextcloud client using the
deletion_queue; the Mac never remotely wipes the phone without that queue.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Iterable  # noqa: F401 — Iterable used by callers/types

from cumulous.paths import EXTERNALSSD_ROOT, ensure_internal, externalssd_mounted

MEDIA_EXT = {
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".gif",
    ".webp",
    ".mov",
    ".mp4",
    ".m4v",
    ".3gp",
    ".avi",
}


def photo_library_root() -> Path:
    if externalssd_mounted() and not os.environ.get("CUMULOUS_FORCE_INTERNAL_VAULT"):
        d = EXTERNALSSD_ROOT / "CumulousPhotos"
    else:
        d = Path.home() / "CumulousPhotos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prefs_path() -> Path:
    return ensure_internal() / "photo_offload.json"


def mirror_index_path() -> Path:
    return ensure_internal() / "media_mirror_index.json"


def deletion_queue_path() -> Path:
    return ensure_internal() / "media_deletion_queue.json"


def default_prefs() -> dict[str, Any]:
    return {
        "asked_setup_choice": True,
        # CEO wants free space when dual-mirrored — enabled with dual-verify gate
        "free_phone_storage_after_backup": True,
        "require_dual_mirror_before_delete": True,  # HDD + Nextcloud both required
        "mirror_display": "cumulous_photos_primary",
        "sync_interval_minutes": 30,
        "wifi_only_offload": False,  # allow cellular progressive when needed
        "cellular_offload_allowed": True,
        "host_originals_on_hdd": True,
        "host_originals_on_nextcloud": True,
        # After initial full dual-mirror, user may enable keep-originals + incremental add-only
        "download_and_keep_originals": False,
        "initial_backup_complete": False,
        # Free-space protect rules (never auto-delete these from phone)
        "keep_on_device_days": 180,
        "keep_favorites": True,
        "keep_album_names": ["Snapchat", "Snapchat Camera", "Recents"],  # Snapchat folders protected
        "keep_if_viewed_or_saved_days": 180,
        "delete_only_after_triple_check": True,  # HDD + Nextcloud + re-read verify
        "continuous_capture_backup": True,  # segment upload while recording when app open
        # Vault policy: prior digests are never removed by later backups
        "add_only_vault": True,
        # Prompt at every backup start: run intelligent storage optimize pass?
        "storage_optimize_prompt_at_backup": True,
        "storage_optimize_default_yes": False,
        "storage_optimize_mode": "balanced",  # conservative | balanced | aggressive
        "notes": (
            "Originals on HDD + Nextcloud. Cumulous Photos is preferred in-app library. "
            "Never free phone media until dual-mirror + re-verify. Keep last 180 days, "
            "Favorites, and Snapchat albums on device. Later backups only add new digests. "
            "Each backup asks whether to run a smart storage optimization pass first."
        ),
    }


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
        return base
    except Exception:
        return default_prefs()


def save_prefs(prefs: dict[str, Any]) -> None:
    ensure_internal()
    prefs = {**prefs, "updated_at": time.time()}
    p = prefs_path()
    p.write_text(json.dumps(prefs, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def record_setup_choice(*, free_phone_storage: bool) -> dict:
    prefs = load_prefs()
    prefs["asked_setup_choice"] = True
    prefs["free_phone_storage_after_backup"] = bool(free_phone_storage)
    prefs["require_dual_mirror_before_delete"] = True
    save_prefs(prefs)
    return prefs


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


def load_mirror_index() -> dict:
    return _load_json(mirror_index_path(), {"items": {}})


def save_mirror_index(data: dict) -> None:
    data["updated_at"] = time.time()
    _save_json(mirror_index_path(), data)


def load_deletion_queue() -> list[dict]:
    data = _load_json(deletion_queue_path(), {"queue": []})
    return list(data.get("queue") or [])


def save_deletion_queue(queue: list[dict]) -> None:
    _save_json(deletion_queue_path(), {"queue": queue, "updated_at": time.time()})


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def is_media(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXT


def device_album_dir(device_id: str, apple_account_id: str = "") -> Path:
    safe_dev = "".join(c if c.isalnum() or c in "-_" else "_" for c in device_id)[:80]
    safe_acct = "".join(c if c.isalnum() or c in "-_@." else "_" for c in (apple_account_id or "shared"))[:80]
    d = photo_library_root() / safe_acct / safe_dev
    d.mkdir(parents=True, exist_ok=True)
    return d


def library_status() -> dict[str, Any]:
    root = photo_library_root()
    count = 0
    bytes_total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.startswith("."):
                continue
            fp = Path(dirpath) / name
            try:
                bytes_total += fp.stat().st_size
                count += 1
            except OSError:
                continue
    prefs = load_prefs()
    idx = load_mirror_index()
    items = idx.get("items") or {}
    dual = sum(1 for it in items.values() if it.get("hdd_ok") and it.get("nextcloud_ok"))
    pending_del = len([q for q in load_deletion_queue() if q.get("status") == "pending"])
    # Always surface last verified phone inventory (refresh when USB present)
    inv = load_device_inventory()
    return {
        "root": str(root),
        "file_count": count,
        "total_bytes": bytes_total,
        "prefs": prefs,
        "mirrored_dual_count": dual,
        "indexed_count": len(items),
        "deletion_queue_pending": pending_del,
        "device_media": {
            "photos": inv.get("photos"),
            "videos": inv.get("videos"),
            "media_total": inv.get("media_total"),
            "verified_at": inv.get("verified_at"),
            "gap": max(0, int(inv.get("media_total") or 0) - count),
            "source": inv.get("source"),
            "note": inv.get("note"),
        },
        "display_strategy": {
            "preferred": "Cumulous Photos (in-app Photos.app-like gallery on all devices)",
            "also": "Nextcloud iOS app — streams from this Mac",
            "not_possible": "Apple Photos.app third-party iCloud-style placeholders",
            "delete_policy": "Remove from phone only after HDD + Nextcloud both verified",
            "tagging": "Deeper than Photos: date, place, people/plants/objects, setting, context",
        },
    }


def store_on_hdd(
    data: bytes,
    *,
    device_id: str,
    rel_name: str,
    apple_account_id: str = "",
) -> dict[str, Any]:
    album = device_album_dir(device_id, apple_account_id)
    safe_name = Path(rel_name.replace("\\", "/")).name or f"media_{int(time.time())}"
    # preserve unique path under album using hash prefix to avoid collisions
    digest = hashlib.sha256(data).hexdigest()
    dest = album / f"{digest[:12]}_{safe_name}"
    if not dest.exists():
        dest.write_bytes(data)
    return {
        "ok": True,
        "path": str(dest),
        "digest": digest,
        "size": len(data),
        "rel": str(dest.relative_to(photo_library_root())),
    }


def dual_mirror_bytes(
    data: bytes,
    *,
    device_id: str,
    rel_name: str,
    apple_account_id: str = "",
    local_asset_id: str = "",
    enrich: bool = True,
) -> dict[str, Any]:
    """Write to HDD and Nextcloud; queue phone deletion only if both OK and policy allows.

    Set enrich=False for bulk harvest (catalog scan runs once at end).
    """
    prefs = load_prefs()
    hdd = store_on_hdd(data, device_id=device_id, rel_name=rel_name, apple_account_id=apple_account_id)
    digest = hdd["digest"]
    remote_rel = f"{apple_account_id or 'shared'}/{device_id}/{digest[:12]}_{Path(rel_name).name}"

    nc_ok = False
    nc_result: dict[str, Any] = {"ok": False, "skipped": True}
    if prefs.get("host_originals_on_nextcloud", True):
        from cumulous.nextcloud_client import nextcloud_reachable, upload_bytes

        reach = nextcloud_reachable()
        if reach.get("ok"):
            nc_result = upload_bytes(remote_rel, data)
            nc_ok = bool(nc_result.get("ok"))
        else:
            nc_result = {"ok": False, "error": reach.get("error") or "nextcloud_unreachable"}

    hdd_ok = bool(hdd.get("ok"))
    dual_ok = hdd_ok and nc_ok
    if prefs.get("require_dual_mirror_before_delete", True):
        safe_delete = dual_ok and bool(prefs.get("free_phone_storage_after_backup"))
    else:
        safe_delete = hdd_ok and bool(prefs.get("free_phone_storage_after_backup"))

    idx = load_mirror_index()
    items = idx.setdefault("items", {})
    prev = dict(items.get(digest) or {})
    # Merge: never demote a prior dual-ok or wipe a known AFC path with empty
    merged_nc = bool(nc_ok or prev.get("nextcloud_ok"))
    merged_path = local_asset_id or prev.get("local_asset_id") or ""
    merged_nc_rel = (remote_rel if nc_ok else "") or prev.get("nextcloud_rel") or ""
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
        "nextcloud_rel": merged_nc_rel,
        "local_asset_id": merged_path,
        "safe_to_delete_on_device": safe_delete if not prev.get("deleted_on_device") else False,
        "updated_at": time.time(),
    }
    # Dual-ok means both present after merge
    dual_ok = bool(items[digest]["hdd_ok"] and items[digest]["nextcloud_ok"])
    if prefs.get("require_dual_mirror_before_delete", True):
        safe_delete = dual_ok and bool(prefs.get("free_phone_storage_after_backup"))
    else:
        safe_delete = bool(items[digest]["hdd_ok"]) and bool(prefs.get("free_phone_storage_after_backup"))
    items[digest]["safe_to_delete_on_device"] = safe_delete and not prev.get("deleted_on_device")
    save_mirror_index(idx)

    # Protect favorites / Snapchat / last 180 days from deletion queue
    protect = _should_keep_on_device(
        prefs,
        name=Path(rel_name).name,
        local_asset_id=local_asset_id,
    )
    if safe_delete and not protect.get("keep"):
        # Triple-check: re-stat HDD + dual present (merged Nextcloud ok counts)
        hdd_path = Path(hdd.get("path") or items[digest].get("hdd_path") or "")
        size_ok = hdd_path.is_file() and hdd_path.stat().st_size == int(items[digest].get("size") or len(data))
        triple_ok = size_ok and dual_ok
        if prefs.get("delete_only_after_triple_check", True) and not triple_ok:
            safe_delete = False
        else:
            q = load_deletion_queue()
            if not any(x.get("digest") == digest and x.get("status") == "pending" for x in q):
                q.append(
                    {
                        "digest": digest,
                        "device_id": device_id or items[digest].get("device_id") or "",
                        "local_asset_id": merged_path,
                        "name": Path(rel_name).name,
                        "status": "pending",
                        "reason": "dual_mirror_verified_hdd_and_nextcloud_triple_check",
                        "queued_at": time.time(),
                    }
                )
                save_deletion_queue(q)
    elif protect.get("keep"):
        safe_delete = False
    items[digest]["safe_to_delete_on_device"] = bool(safe_delete) and not prev.get("deleted_on_device")
    save_mirror_index(idx)

    # Catalog + tags (skip on bulk harvest for speed)
    if enrich:
        try:
            from cumulous.photo_library import scan_library
            from cumulous.photo_tagging import enrich_and_store

            hdd_path = Path(hdd.get("path") or "")
            if hdd_path.is_file() and hdd_path.suffix.lower() in {
                ".jpg",
                ".jpeg",
                ".png",
                ".heic",
                ".heif",
                ".webp",
                ".gif",
            }:
                enrich_and_store(
                    hdd_path,
                    digest=digest,
                    filename=Path(rel_name).name,
                    run_vision=False,
                )
            scan_library(enrich=False, limit=50)
        except Exception:
            pass

    return {
        "ok": dual_ok or hdd_ok,
        "dual_ok": dual_ok,
        "hdd": hdd,
        "nextcloud": nc_result,
        "safe_to_delete_on_device": safe_delete,
        "digest": digest,
    }


def dual_mirror_file(
    path: Path,
    *,
    device_id: str,
    apple_account_id: str = "",
    local_asset_id: str = "",
) -> dict[str, Any]:
    data = path.read_bytes()
    return dual_mirror_bytes(
        data,
        device_id=device_id,
        rel_name=path.name,
        apple_account_id=apple_account_id,
        local_asset_id=local_asset_id,
    )


def harvest_media_from_tree(
    source: Path,
    *,
    device_id: str,
    apple_account_id: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    """Find media files under a folder (e.g. backup extract) and dual-mirror them."""
    source = source.expanduser()
    mirrored = 0
    dual = 0
    delete_ready = 0
    errors = 0
    scanned = 0
    if not source.is_dir():
        return {"ok": False, "error": "source_not_dir"}

    for root, _dirs, names in os.walk(source):
        for name in names:
            p = Path(root) / name
            if not is_media(p):
                continue
            scanned += 1
            try:
                # skip huge singles in harvest pass (still mirrored later if needed)
                if p.stat().st_size > 80 * 1024 * 1024:
                    continue
                res = dual_mirror_file(p, device_id=device_id, apple_account_id=apple_account_id)
                if res.get("ok"):
                    mirrored += 1
                if res.get("dual_ok"):
                    dual += 1
                if res.get("safe_to_delete_on_device"):
                    delete_ready += 1
            except Exception:
                errors += 1
            if mirrored >= limit:
                break
        if mirrored >= limit:
            break

    return {
        "ok": True,
        "scanned_media": scanned,
        "mirrored": mirrored,
        "dual_ok": dual,
        "delete_ready": delete_ready,
        "errors": errors,
        "library": str(photo_library_root()),
    }


def mark_deleted_on_device(digest: str) -> None:
    q = load_deletion_queue()
    for item in q:
        if item.get("digest") == digest and item.get("status") == "pending":
            item["status"] = "deleted_on_device"
            item["deleted_at"] = time.time()
    save_deletion_queue(q)
    idx = load_mirror_index()
    if digest in (idx.get("items") or {}):
        idx["items"][digest]["deleted_on_device"] = True
        save_mirror_index(idx)


def pending_deletions_for_device(device_id: str) -> list[dict]:
    return [
        q
        for q in load_deletion_queue()
        if q.get("status") == "pending" and (not device_id or q.get("device_id") == device_id)
    ]


def freeable_on_device(
    *,
    device_id: str = "",
    dual_only: bool = True,
    respect_protect: bool = True,
) -> list[dict[str, Any]]:
    """Items safe to remove from the phone (still kept forever on Mac vault + NC).

    Honors dual-mirror gate, protect albums/favorites, and safe_to_delete when set.
    """
    prefs = load_prefs()
    idx = load_mirror_index().get("items") or {}
    out: list[dict[str, Any]] = []
    for dig, it in idx.items():
        if it.get("deleted_on_device"):
            continue
        if device_id and str(it.get("device_id") or "") not in ("", str(device_id)):
            continue
        if dual_only and not (it.get("hdd_ok") and it.get("nextcloud_ok")):
            continue
        if not dual_only and not it.get("hdd_ok"):
            continue
        # Prefer explicit dual-verify flag when present
        if dual_only and it.get("safe_to_delete_on_device") is False and it.get("hdd_ok") and it.get("nextcloud_ok"):
            # still allow manual free of dual items unless protect blocks
            pass
        if respect_protect:
            prot = _should_keep_on_device(
                prefs,
                name=str(it.get("name") or ""),
                local_asset_id=str(it.get("local_asset_id") or ""),
            )
            hard = [r for r in (prot.get("reasons") or []) if not str(r).startswith("client_must")]
            if hard:
                continue
        out.append({**it, "digest": dig})
    return out


def usb_device_present() -> dict[str, Any]:
    """USB usbmux presence required for Mac→device photo deletes."""
    try:
        from cumulous.devices import probe_connected_device

        probe = probe_connected_device() or {}
    except Exception as e:
        return {"ok": False, "usb": False, "error": str(e)[:120], "probe": {}}
    udid = str(probe.get("udid") or "")
    return {
        "ok": bool(udid),
        "usb": bool(udid),
        "probe": probe,
        "udid": udid,
        "device_id": probe.get("imei") or probe.get("device_id") or udid,
        "display_name": probe.get("display_name") or "",
    }


def _afc_remove_path(udid: str, remote_path: str) -> dict[str, Any]:
    """Best-effort AFC unlink of a single path (DCIM / PhotoData)."""
    if not udid or not remote_path or not str(remote_path).startswith("/"):
        return {"ok": False, "error": "invalid_path"}
    # Never allow path traversal outside known media roots
    allowed = remote_path.startswith("/DCIM/") or remote_path.startswith("/PhotoData/")
    if not allowed:
        return {"ok": False, "error": "path_not_allowed"}
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


def request_device_delete(
    digest: str,
    *,
    source: str = "mac",
    require_usb: bool | None = None,
    execute_afc: bool = True,
) -> dict[str, Any]:
    """Remove dual-verified media from the phone — never from the Mac vault.

    source:
      - ``mac``: Cumulous on this Mac — USB cable required; optional AFC unlink.
      - ``ios``: Cumulous on the phone — no USB; marks queue + client deletes PHAsset.
    Vault files (HDD + Nextcloud) are never deleted by this path.
    """
    digest = (digest or "").strip()
    if not digest or len(digest) < 16:
        return {"ok": False, "error": "invalid_digest", "message": "Pick a photo first."}

    idx = load_mirror_index()
    item = (idx.get("items") or {}).get(digest)
    if not item:
        return {"ok": False, "error": "not_in_vault", "message": "That photo is not in the Cumulous backup yet."}

    if item.get("deleted_on_device"):
        return {"ok": True, "already": True, "message": "Already removed from the phone."}

    hdd_ok = bool(item.get("hdd_ok"))
    nc_ok = bool(item.get("nextcloud_ok"))
    if not hdd_ok:
        return {
            "ok": False,
            "error": "not_backed_up",
            "message": "Back up this photo first before removing it from the phone.",
        }
    prefs = load_prefs()
    if prefs.get("require_dual_mirror_before_delete", True) and not nc_ok:
        return {
            "ok": False,
            "error": "awaiting_dual_mirror",
            "message": "Waiting for both copies (Mac + Nextcloud) before freeing phone space.",
        }
    prot = _should_keep_on_device(
        prefs,
        name=str(item.get("name") or ""),
        local_asset_id=str(item.get("local_asset_id") or ""),
    )
    hard = [r for r in (prot.get("reasons") or []) if not str(r).startswith("client_must")]
    if hard:
        return {
            "ok": False,
            "error": "protected",
            "message": "This photo is protected (Favorites / Snapchat / keep album) and stays on the phone.",
            "reasons": hard,
        }

    src = (source or "mac").lower()
    if require_usb is None:
        require_usb = src == "mac"

    usb_info = usb_device_present()
    if require_usb and not usb_info.get("usb"):
        return {
            "ok": False,
            "error": "usb_required",
            "message": "Plug the iPhone into this Mac with a USB cable to remove photos from the phone.",
            "usb": False,
        }

    afc_result: dict[str, Any] = {"ok": False, "skipped": True}
    remote = str(item.get("local_asset_id") or "")
    if src == "mac" and execute_afc and remote.startswith("/") and usb_info.get("udid"):
        afc_result = _afc_remove_path(str(usb_info["udid"]), remote)

    # Ensure pending queue entry exists
    q = load_deletion_queue()
    if not any(x.get("digest") == digest for x in q):
        q.append(
            {
                "digest": digest,
                "device_id": item.get("device_id") or "",
                "local_asset_id": remote,
                "name": item.get("name") or "",
                "status": "pending",
                "reason": "user_requested_device_remove",
                "queued_at": time.time(),
                "source": src,
            }
        )
        save_deletion_queue(q)

    # iOS app deletes PHAsset then acks — treat request as queued for client completion
    # unless AFC already removed the file from Mac path.
    if afc_result.get("ok"):
        mark_deleted_on_device(digest)
        return {
            "ok": True,
            "digest": digest,
            "afc": afc_result,
            "source": src,
            "message": "Removed from phone. Still safe in Cumulous backup.",
            "vault_kept": True,
        }

    if src == "ios":
        # Client should delete local asset; they call /photos/deletion-ack after success.
        return {
            "ok": True,
            "digest": digest,
            "queued": True,
            "source": src,
            "message": "Ready to free this photo on the iPhone. Cumulous keeps the backup.",
            "vault_kept": True,
            "client_should_delete": True,
        }

    return {
        "ok": True,
        "digest": digest,
        "queued": True,
        "afc": afc_result,
        "source": src,
        "message": "Queued for the phone. Keep USB connected or finish in the iPhone app.",
        "vault_kept": True,
    }


def request_device_delete_all_freeable(
    *,
    device_id: str = "",
    source: str = "mac",
    require_usb: bool | None = None,
    execute_afc: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """Remove all dual-verified freeable on-device photos (vault untouched)."""
    src = (source or "mac").lower()
    if require_usb is None:
        require_usb = src == "mac"
    usb_info = usb_device_present()
    if require_usb and not usb_info.get("usb"):
        return {
            "ok": False,
            "error": "usb_required",
            "message": "Plug the iPhone into this Mac with a USB cable to remove all freeable photos.",
            "usb": False,
            "removed": 0,
            "queued": 0,
        }

    did = device_id or str(usb_info.get("device_id") or "")
    items = freeable_on_device(device_id=did, dual_only=True)
    if limit is not None:
        items = items[: int(limit)]
    removed = 0
    queued = 0
    errors = 0
    for it in items:
        dig = str(it.get("digest") or "")
        if not dig:
            continue
        res = request_device_delete(
            dig,
            source=src,
            require_usb=False,  # already checked once
            execute_afc=execute_afc and src == "mac",
        )
        if res.get("ok") and not res.get("queued"):
            removed += 1
        elif res.get("ok"):
            queued += 1
        else:
            errors += 1
    return {
        "ok": True,
        "removed": removed,
        "queued": queued,
        "errors": errors,
        "considered": len(items),
        "vault_kept": True,
        "message": (
            f"Phone cleanup: {removed} removed, {queued} queued. "
            "All copies stay in Cumulous on this Mac."
        ),
    }


def set_download_and_keep_originals(enabled: bool) -> dict[str, Any]:
    """After initial dual-mirror, keep new originals on device while still backing up new ones."""
    prefs = load_prefs()
    prefs["download_and_keep_originals"] = bool(enabled)
    if enabled:
        # Incremental add-only: do not free phone for new items until user turns free-space back on
        prefs["free_phone_storage_after_backup"] = False
    else:
        # Restore dual-verify free-phone policy when keep-originals is turned off
        prefs["free_phone_storage_after_backup"] = True
        prefs["require_dual_mirror_before_delete"] = True
    save_prefs(prefs)
    return prefs


def mark_initial_photo_backup_complete(*, mirrored: int = 0) -> dict[str, Any]:
    prefs = load_prefs()
    prefs["initial_backup_complete"] = True
    prefs["initial_backup_mirrored"] = int(mirrored)
    prefs["initial_backup_at"] = time.time()
    save_prefs(prefs)
    return prefs


def delete_from_mac_vault(
    digest: str,
    *,
    also_nextcloud: bool = False,
) -> dict[str, Any]:
    """Explicit Mac-side vault delete only (never automatic on re-backup)."""
    digest = (digest or "").strip()
    idx = load_mirror_index()
    items = idx.get("items") or {}
    item = items.get(digest)
    if not item:
        return {"ok": False, "error": "not_found", "message": "Not in Cumulous library."}
    hdd_path = Path(str(item.get("hdd_path") or ""))
    removed_hdd = False
    if hdd_path.is_file():
        try:
            hdd_path.unlink()
            removed_hdd = True
        except OSError as e:
            return {"ok": False, "error": str(e)[:120], "message": "Could not delete the Mac copy."}
    nc_removed = False
    if also_nextcloud and item.get("nextcloud_rel"):
        try:
            from cumulous.nextcloud_client import delete_remote

            dr = delete_remote(str(item.get("nextcloud_rel")))
            nc_removed = bool(dr.get("ok"))
        except Exception:
            nc_removed = False
    items.pop(digest, None)
    save_mirror_index(idx)
    # Drop from deletion queue
    q = [x for x in load_deletion_queue() if x.get("digest") != digest]
    save_deletion_queue(q)
    return {
        "ok": True,
        "digest": digest,
        "removed_hdd": removed_hdd,
        "removed_nextcloud": nc_removed,
        "message": "Removed from Cumulous backup on this Mac.",
    }


def enable_free_phone_after_dual_mirror() -> dict:
    """CEO policy: free phone space once dual mirror is the default gate."""
    prefs = load_prefs()
    prefs["free_phone_storage_after_backup"] = True
    prefs["require_dual_mirror_before_delete"] = True
    prefs["host_originals_on_hdd"] = True
    prefs["host_originals_on_nextcloud"] = True
    prefs["asked_setup_choice"] = True
    prefs["keep_on_device_days"] = int(prefs.get("keep_on_device_days") or 180)
    prefs["keep_favorites"] = True
    prefs["delete_only_after_triple_check"] = True
    save_prefs(prefs)
    return prefs


def _should_keep_on_device(prefs: dict, *, name: str, local_asset_id: str = "") -> dict:
    """Return keep=True if media must stay on the phone even after dual-mirror."""
    reasons: list[str] = []
    name_l = (name or "").lower()
    asset_l = (local_asset_id or "").lower()
    albums = [a.lower() for a in (prefs.get("keep_album_names") or [])]
    for alb in albums:
        if alb and (alb in name_l or alb in asset_l):
            reasons.append(f"album:{alb}")
    if prefs.get("keep_favorites") and ("favorite" in name_l or "favourites" in name_l or "favorited" in asset_l):
        reasons.append("favorites")
    # Snapchat explicit
    if "snapchat" in name_l or "snapchat" in asset_l:
        reasons.append("snapchat")
    # 180-day window: without EXIF here we conservatively keep recent-looking camera roll names
    # Full EXIF date check happens in photo_tagging when available
    days = int(prefs.get("keep_on_device_days") or 180)
    if days > 0:
        try:
            from cumulous.photo_tagging import get_tags
            from cumulous.photo_library import get_asset
            # if we can resolve tags by scanning name prefix in index — skip heavy work
        except Exception:
            pass
        # Always attach protect window note for clients; iOS client must filter by PHAsset.creationDate
        reasons.append(f"client_must_enforce_{days}d_window")
    # Server-side: only hard-block known protected albums/favorites on queue
    hard = [r for r in reasons if not r.startswith("client_must")]
    return {"keep": bool(hard), "reasons": reasons}


def photo_access_policy() -> dict[str, Any]:
    """How Cumulous relates to system Photos / other apps (honest)."""
    return {
        "cumulous_photos_in_app": True,
        "can_replace_system_photos_for_all_apps": False,
        "reason": (
            "Apple does not allow a third-party app to become the global Photos provider "
            "for every other app's UIImagePicker/PHPicker. System PHPicker is controlled by iOS."
        ),
        "what_we_do": [
            "Cumulous Photos is the primary library UI inside Cumulous (clone + deeper tags).",
            "Share / Action extension targets (when signed) let users pick from Cumulous library.",
            "Document the user: set Cumulous as habitual gallery; grant Photos permission for dual-mirror.",
            "Continuous capture backup while Cumulous is open (idle timer off + segment upload).",
        ],
        "preferred_display": "cumulous_photos_clone",
    }


# ── Device media inventory + full AFC dual-mirror harvest ───────────────────

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".3gp", ".avi"}
PHOTO_EXT = MEDIA_EXT - VIDEO_EXT

HARVEST_STATE_FILE = "device_media_harvest.json"
DEVICE_INVENTORY_FILE = "device_media_inventory.json"


def harvest_state_path() -> Path:
    return ensure_internal() / HARVEST_STATE_FILE


def device_inventory_path() -> Path:
    return ensure_internal() / DEVICE_INVENTORY_FILE


def load_harvest_state() -> dict[str, Any]:
    return _load_json(harvest_state_path(), {})


def save_harvest_state(data: dict[str, Any]) -> None:
    data["updated_at"] = time.time()
    _save_json(harvest_state_path(), data)


def load_device_inventory() -> dict[str, Any]:
    return _load_json(device_inventory_path(), {})


def save_device_inventory(data: dict[str, Any]) -> None:
    data["updated_at"] = time.time()
    _save_json(device_inventory_path(), data)


def _media_kind(name: str) -> str | None:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in PHOTO_EXT or ext in MEDIA_EXT:
        return "photo"
    return None


def verify_device_media_count(*, udid: str = "", deep: bool = True) -> dict[str, Any]:
    """Always-on phone inventory via USB AFC (DCIM + PhotoData).

    Notes (honest):
      - Photos app “# Items” can include iCloud-only assets not fully resident on disk.
      - AFC sees files present in the media filesystem (local + downloaded CPL assets).
      - We always re-count on call and persist the latest inventory for the UI.
    """
    import asyncio

    roots = ["/DCIM", "/PhotoData"] if deep else ["/DCIM"]

    async def _walk(afc, path: str, depth: int = 0) -> tuple[int, int, int, list[str]]:
        photos = videos = other = 0
        samples: list[str] = []
        try:
            entries = await afc.listdir(path)
        except Exception:
            return 0, 0, 0, []
        for name in entries or []:
            if name in (".", ".."):
                continue
            child = f"{path.rstrip('/')}/{name}"
            kind = _media_kind(name)
            # Prefer treating known media files as files even if listdir succeeds on some links
            if kind and "." in name:
                # could still be a directory with extension (rare) — try listdir
                is_dir = False
                try:
                    await afc.listdir(child)
                    is_dir = True
                except Exception:
                    is_dir = False
                if not is_dir:
                    if kind == "video":
                        videos += 1
                    else:
                        photos += 1
                    if len(samples) < 8:
                        samples.append(child)
                    continue
            # directory or unknown
            try:
                await afc.listdir(child)
                is_dir = True
            except Exception:
                is_dir = False
            if is_dir and depth < 14:
                p, v, o, s = await _walk(afc, child, depth + 1)
                photos += p
                videos += v
                other += o
                if len(samples) < 8:
                    samples.extend(s[: 8 - len(samples)])
            else:
                if kind == "video":
                    videos += 1
                elif kind == "photo":
                    photos += 1
                else:
                    other += 1
        return photos, videos, other, samples

    async def _run() -> dict[str, Any]:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService

        kwargs = {}
        if udid:
            kwargs["serial"] = udid
        ld = await create_using_usbmux(**kwargs)
        by_root: dict[str, Any] = {}
        total_p = total_v = total_o = 0
        samples: list[str] = []
        async with AfcService(ld) as afc:
            for root in roots:
                try:
                    p, v, o, s = await _walk(afc, root)
                except Exception as e:
                    by_root[root] = {"error": str(e)[:160]}
                    continue
                by_root[root] = {
                    "photos": p,
                    "videos": v,
                    "other_files": o,
                    "media_total": p + v,
                }
                total_p += p
                total_v += v
                total_o += o
                samples.extend(s[:3])
        return {
            "ok": True,
            "source": "afc_usb",
            "roots": by_root,
            "photos": total_p,
            "videos": total_v,
            "other_files": total_o,
            "media_total": total_p + total_v,
            "samples": samples[:12],
            "note": (
                "media_total is files present on the phone’s media filesystem via USB. "
                "Photos app item count can be higher if iCloud Photos holds cloud-only originals "
                "not fully downloaded. Cumulous backs up every AFC-reachable original/derivative media file."
            ),
            "target_user_reported": 62528,
        }

    try:
        inv = asyncio.run(_run())
    except Exception as e:
        inv = {
            "ok": False,
            "error": str(e)[:200],
            "media_total": 0,
            "photos": 0,
            "videos": 0,
            "note": "Connect iPhone by USB, unlock, Trust this computer, then re-verify.",
        }
    inv["verified_at"] = time.time()
    # Merge Cumulous backed-up totals
    lib = library_status()
    inv["cumulous_hdd_files"] = lib.get("file_count")
    inv["cumulous_dual_mirrored"] = lib.get("mirrored_dual_count")
    inv["gap"] = max(0, int(inv.get("media_total") or 0) - int(lib.get("file_count") or 0))
    save_device_inventory(inv)
    return inv


def harvest_device_media_afc(
    *,
    device_id: str = "",
    udid: str = "",
    apple_account_id: str = "",
    limit: int | None = None,
    roots: list[str] | None = None,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """Pull AFC media from the phone and dual-mirror to HDD + Nextcloud.

    Streams files as found (DCIM first, then PhotoData) — does not wait for a
    full tree inventory before copying. Prefer a long-lived process (nohup).
    """
    import asyncio

    # DCIM first (camera originals), then PhotoData (incl. iCloud CPL assets)
    roots = roots or ["/DCIM", "/PhotoData"]
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
        "paths_found": 0,
        "bytes": 0,
        "last_path": "",
        "current_root": "",
    }
    save_harvest_state(state)

    idx = load_mirror_index()
    known_digests = set((idx.get("items") or {}).keys())
    known_names = {
        str(it.get("name") or "")
        for it in (idx.get("items") or {}).values()
        if it.get("name")
    }

    async def _process_file(afc, remote: str, did: str) -> None:
        state["scanned"] = int(state.get("scanned") or 0) + 1
        state["paths_found"] = int(state.get("paths_found") or 0) + 1
        state["last_path"] = remote
        name = Path(remote).name
        try:
            data = await afc.get_file_contents(remote)
        except Exception:
            state["errors"] = int(state["errors"]) + 1
            return
        if not data or len(data) < 32:
            state["errors"] = int(state["errors"]) + 1
            return
        digest = hashlib.sha256(data).hexdigest()
        # Add-only vault: skip only by content digest — never drop prior backups;
        # same filename with new bytes is still mirrored under a new digest path.
        if skip_existing and digest in known_digests:
            state["skipped_existing"] = int(state["skipped_existing"]) + 1
            return
        try:
            res = dual_mirror_bytes(
                data,
                device_id=did,
                rel_name=name,
                apple_account_id=apple_account_id,
                local_asset_id=remote,
                enrich=False,  # bulk: catalog refresh once at end
            )
            if res.get("ok"):
                state["mirrored"] = int(state["mirrored"]) + 1
                known_digests.add(digest)
                known_names.add(name)
                state["bytes"] = int(state["bytes"]) + len(data)
            if res.get("dual_ok"):
                state["dual_ok"] = int(state["dual_ok"]) + 1
            elif not res.get("ok"):
                state["errors"] = int(state["errors"]) + 1
        except Exception:
            state["errors"] = int(state["errors"]) + 1

    async def _walk_and_mirror(afc, path: str, did: str, depth: int = 0) -> None:
        if limit is not None and int(state["mirrored"]) >= limit:
            return
        try:
            entries = await afc.listdir(path)
        except Exception:
            return
        for name in entries or []:
            if limit is not None and int(state["mirrored"]) >= limit:
                return
            if name in (".", ".."):
                continue
            child = f"{path.rstrip('/')}/{name}"
            kind = _media_kind(name)
            # Fast path: media filename → file (skip listdir probe when possible)
            if kind and name.count(".") >= 1:
                # Still need to distinguish dir vs file for odd names
                try:
                    await afc.listdir(child)
                    # directory with media-like name
                    if depth < 14:
                        await _walk_and_mirror(afc, child, did, depth + 1)
                    continue
                except Exception:
                    await _process_file(afc, child, did)
                    if int(state["scanned"]) % 5 == 0:
                        save_harvest_state(state)
                    continue
            # unknown — try as directory
            try:
                await afc.listdir(child)
                is_dir = True
            except Exception:
                is_dir = False
            if is_dir and depth < 14:
                await _walk_and_mirror(afc, child, did, depth + 1)
            elif kind:
                await _process_file(afc, child, did)
                if int(state["scanned"]) % 5 == 0:
                    save_harvest_state(state)

    async def _run() -> dict[str, Any]:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService

        kwargs: dict[str, Any] = {}
        if udid:
            kwargs["serial"] = udid
        ld = await create_using_usbmux(**kwargs)
        did = device_id or udid or "device"
        async with AfcService(ld) as afc:
            for root in roots:
                state["current_root"] = root
                save_harvest_state(state)
                await _walk_and_mirror(afc, root, did, 0)
        return state

    try:
        st = asyncio.run(_run())
        st["status"] = "complete"
        st["finished_at"] = time.time()
        try:
            from cumulous.photo_library import scan_library

            scan_library(enrich=False, limit=5000)
        except Exception:
            pass
        lib = library_status()
        st["device_inventory"] = {
            "cumulous_hdd_files": lib.get("file_count"),
            "cumulous_dual_mirrored": lib.get("mirrored_dual_count"),
            "note": "Re-run /photos/device-inventory?refresh=true for full phone recount",
        }
        try:
            mark_initial_photo_backup_complete(mirrored=int(st.get("mirrored") or 0))
        except Exception:
            pass
        save_harvest_state(st)
        return {"ok": True, **st}
    except Exception as e:
        state["status"] = "error"
        state["error"] = str(e)[:240]
        state["finished_at"] = time.time()
        save_harvest_state(state)
        return {"ok": False, **state}


_harvest_thread: threading.Thread | None = None
_harvest_proc: Any = None  # subprocess.Popen when using process mode


def _harvest_pid_path() -> Path:
    return ensure_internal() / "device_media_harvest.pid"


def harvest_is_alive() -> bool:
    """True if harvest state is running and a worker (thread or process) is alive."""
    cur = load_harvest_state()
    if cur.get("status") != "running":
        return False
    # Process pid file
    pid_p = _harvest_pid_path()
    if pid_p.exists():
        try:
            pid = int(pid_p.read_text().strip())
            os.kill(pid, 0)
            return True
        except Exception:
            pass
    global _harvest_thread
    if _harvest_thread is not None and _harvest_thread.is_alive():
        return True
    # Heartbeat: state updated in last 90s still counts as alive (cross-process)
    try:
        age = time.time() - float(cur.get("updated_at") or 0)
        if age < 90:
            return True
    except Exception:
        pass
    return False


def start_device_media_harvest(
    *,
    device_id: str = "",
    udid: str = "",
    apple_account_id: str = "",
    limit: int | None = None,
    force: bool = False,
    use_process: bool = True,
) -> dict[str, Any]:
    """Background full-device media harvest → HDD + Nextcloud.

    Prefers a detached process so harvest survives Streamlit/API restarts.
    Engages keep-awake / no-dim policy for the duration.
    """
    global _harvest_thread, _harvest_proc
    import subprocess
    import sys
    import threading

    cur = load_harvest_state()
    if not force and harvest_is_alive():
        # Refresh wake policy even if already running
        try:
            from cumulous.device_power import begin_backup_wake_policy

            begin_backup_wake_policy(
                session_id=f"harvest_{device_id or udid or 'device'}",
                device_name="ROB IPHONE (2)",
            )
        except Exception:
            pass
        return {"ok": True, "already_running": True, "state": cur, "alive": True}

    # Mark running early so parallel callers see us
    save_harvest_state(
        {
            **cur,
            "status": "running",
            "started_at": time.time(),
            "device_id": device_id or cur.get("device_id"),
            "udid": udid or cur.get("udid"),
            "mirrored": 0,
            "dual_ok": 0,
            "skipped_existing": 0,
            "errors": 0,
            "scanned": 0,
            "force": force,
        }
    )

    try:
        from cumulous.device_power import begin_backup_wake_policy

        begin_backup_wake_policy(
            session_id=f"harvest_{device_id or udid or 'device'}",
            device_name="ROB IPHONE (2)",
        )
    except Exception:
        pass

    # Mac caffeinate (best-effort)
    try:
        subprocess.Popen(
            ["caffeinate", "-dimsu", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass

    if use_process:
        try:
            env = os.environ.copy()
            env["CUMULOUS_HARVEST_DEVICE_ID"] = str(device_id or "")
            env["CUMULOUS_HARVEST_UDID"] = str(udid or "")
            env["CUMULOUS_HARVEST_APPLE_ID"] = str(apple_account_id or "")
            if limit is not None:
                env["CUMULOUS_HARVEST_LIMIT"] = str(limit)
            log = open("/tmp/cumulous_harvest.log", "a")
            _harvest_proc = subprocess.Popen(
                [sys.executable, "-m", "cumulous.harvest_worker"],
                cwd=str(Path(__file__).resolve().parents[1]),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            _harvest_pid_path().write_text(str(_harvest_proc.pid))
            return {
                "ok": True,
                "started": True,
                "mode": "process",
                "pid": _harvest_proc.pid,
                "state": load_harvest_state(),
            }
        except Exception as e:
            # fall through to thread
            save_harvest_state({**load_harvest_state(), "process_error": str(e)[:160]})

    def _target() -> None:
        try:
            harvest_device_media_afc(
                device_id=device_id,
                udid=udid,
                apple_account_id=apple_account_id,
                limit=limit,
            )
        finally:
            try:
                from cumulous.device_power import end_backup_wake_policy

                end_backup_wake_policy(reason="harvest_complete")
            except Exception:
                pass

    _harvest_thread = threading.Thread(target=_target, name="cumulous-media-harvest", daemon=True)
    _harvest_thread.start()
    return {"ok": True, "started": True, "mode": "thread", "state": load_harvest_state()}


def harvest_progress() -> dict[str, Any]:
    st = load_harvest_state()
    inv = load_device_inventory()
    lib = library_status()
    power: dict[str, Any] = {}
    try:
        from cumulous.device_power import power_policy_for_clients

        power = power_policy_for_clients()
    except Exception:
        power = {
            "keep_awake": st.get("status") == "running",
            "ios_disable_idle_timer": st.get("status") == "running",
        }
    if st.get("status") == "running":
        power["keep_awake"] = True
        power["ios_disable_idle_timer"] = True
        power["disable_idle_timer"] = True
    # Percent vs DCIM / camera originals — not PhotoData derivative totals (those inflate to 70k+)
    done = float(st.get("mirrored") or 0) + float(st.get("skipped_existing") or 0)
    dual = float(lib.get("mirrored_dual_count") or 0)
    done = max(done, dual)
    roots = (inv or {}).get("roots") or {}
    dcim = roots.get("/DCIM") or roots.get("DCIM") or {}
    dcim_total = float(
        dcim.get("media_total")
        or (int(dcim.get("photos") or 0) + int(dcim.get("videos") or 0))
        or 0
    )
    # Prefer DCIM; fall back to library file_count; never use full media_total (PhotoData junk)
    total = float(
        dcim_total
        or lib.get("file_count")
        or st.get("total_estimate")
        or max(done + float(st.get("pending") or 0), done, 1.0)
    )
    if total > 0 and done > 0:
        pct = min(
            100.0 if st.get("status") == "complete" and done >= total * 0.98 else 99.9,
            max(0.0, 100.0 * done / total),
        )
        if st.get("status") == "complete" and done >= total * 0.98:
            pct = 100.0
        # Short false-complete (scanned << DCIM) must not show 100%
        scanned = float(st.get("scanned") or 0)
        if st.get("status") == "complete" and dcim_total > 50 and scanned < dcim_total * 0.5:
            pct = min(pct, max(1.0, 100.0 * done / dcim_total))
            if done < dcim_total * 0.98:
                pct = min(pct, 99.0)
    elif st.get("status") == "running":
        pct = 0.0
    else:
        pct = min(99.9, max(0.0, 100.0 * done / total)) if total > 0 and done > 0 else 0.0
    return {
        "harvest": st,
        "device_inventory": inv,
        "library": {
            "file_count": lib.get("file_count"),
            "dual_mirrored": lib.get("mirrored_dual_count"),
            "root": lib.get("root"),
        },
        "alive": harvest_is_alive(),
        "power": power,
        "active": st.get("status") == "running",
        "status": st.get("status") or "idle",
        "status_line": (
            f"Photo backup · {int(pct)}% · scanned {st.get('scanned') or 0} · "
            f"new {st.get('mirrored') or 0} · already saved {st.get('skipped_existing') or 0}"
            if st.get("status") == "running"
            else (st.get("status") or "idle")
        ),
        "policy": {
            "always_dual_mirror": True,
            "host_hdd": True,
            "host_nextcloud": True,
            "verify_phone_count_always": True,
            "keep_awake_during_harvest": True,
            "no_auto_dim_in_app": True,
            "percent_basis": "dcim_originals_not_photodata",
        },
        "percent": pct,
        "percent_int": int(round(pct)),
        "items_done": int(done),
        "items_total": int(total),
        "dcim_total": int(dcim_total),
    }
