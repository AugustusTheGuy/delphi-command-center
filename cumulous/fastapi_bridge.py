"""FastAPI bridge: iOS ↔ companion over USB, Wi‑Fi, or cellular (Tailscale)."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cumulous import __version__
from cumulous.agents_registry import dashboard_rows, roster_count
from cumulous.auth import authenticate, bearaccount_exists, create_bearaccount, create_user
from cumulous.challenge_codes import spawn_challenge, spawn_challenge_for_user, verify_challenge
from cumulous.device_bridge import fingerprint_files, verify_against_generation
from cumulous.devices import ceo_override_device_ids, devices_for_user, register_device
from cumulous.network_backup import backup_endpoints, enable_wifi_sync_hint, load_network_prefs
from cumulous.photo_offload import library_status, load_prefs as load_photo_prefs
from cumulous.progressive_backup import create_generation
from cumulous.totp_2fa import load_secret, provisioning_uri, verify_totp

app = FastAPI(title="Cumulous Bridge", version=__version__)

_APP_STATIC = Path(__file__).resolve().parent / "assets" / "app"
if _APP_STATIC.is_dir():
    app.mount("/app/assets", StaticFiles(directory=str(_APP_STATIC)), name="cumulous_app_assets")


class LoginBody(BaseModel):
    username: str
    password: str
    totp_code: str | None = None


class BearBody(BaseModel):
    username: str
    password: str


class UserBody(BaseModel):
    username: str
    password: str
    apple_id_hint: str = ""
    device_ids: list[str] = Field(default_factory=list)


class ChallengeBody(BaseModel):
    purpose: str = "ceo_override"
    requesting_user_id: str
    user_device_ids: list[str] = Field(default_factory=list)
    ceo_override_device_ids: list[str] = Field(default_factory=list)


class VerifyChallengeBody(BaseModel):
    code: str
    purpose: str | None = None


class BackupBody(BaseModel):
    device_id: str
    password: str
    files: dict[str, str]  # path -> utf-8 or base64 text for API simplicity
    mode: str = "persistent"
    categories: list[str] = Field(default_factory=lambda: ["photos", "files", "sms", "notes"])
    encoding: str = "utf-8"  # utf-8 | base64 — base64 for binary photos over Wi‑Fi/cellular
    transport: str = "network"  # usb | wifi | cellular | network
    apple_account_id: str = ""


@app.get("/health")
def health() -> dict[str, Any]:
    from cumulous.backup_session import session_public_view

    return {
        "ok": True,
        "product": "Cumulous",
        "version": __version__,
        "bearaccount_ready": bearaccount_exists(),
        "endpoints": backup_endpoints(),
        "network_prefs": load_network_prefs(),
        "photo_library": library_status(),
        "backup": session_public_view(),
    }


@app.get("/app/version.json")
@app.get("/version")
def api_version(device_id: str = "", platform: str = "ios") -> dict[str, Any]:
    """Always-latest version + icon etag + splash timing (checked every launch).

    When device_id is provided, persistently records that install's version.
    """
    from cumulous.app_update import on_app_launch, package_version, record_device_install

    payload = on_app_launch()
    if device_id:
        rec = record_device_install(
            device_id=device_id,
            version=package_version(),
            platform=platform or "ios",
            source="version_check",
        )
        payload["this_device"] = {
            "device_id": rec.get("device_id"),
            "version": rec.get("version"),
            "up_to_date": rec.get("up_to_date"),
            "last_seen_at": rec.get("last_seen_at"),
        }
    return payload


@app.get("/backup/progress")
def api_backup_progress() -> dict[str, Any]:
    """Live percent + status for Mac mini-window and iOS Home banner."""
    from cumulous.backup_session import session_public_view

    return session_public_view()


@app.post("/backup/start")
def api_backup_start(force_new: bool = False) -> dict[str, Any]:
    """Start/resume full multi-transport backup for the connected iPhone."""
    from cumulous.backup_session import start_full_backup
    from cumulous.devices import probe_connected_device

    probe = probe_connected_device() or {}
    return start_full_backup(
        device_name=probe.get("display_name") or "",
        device_id=probe.get("imei") or probe.get("udid") or "",
        udid=probe.get("udid") or "",
        force_new=force_new,
    )


@app.post("/backup/cancel")
def api_backup_cancel() -> dict[str, Any]:
    from cumulous.backup_session import cancel_backup

    return cancel_backup()


class PowerSnapshotBody(BaseModel):
    auto_lock_seconds: int | None = None  # 0 = Never; 30/60/120/…
    idle_timer_disabled_before: bool | None = None
    device_id: str = ""


@app.post("/backup/power/snapshot")
def api_power_snapshot(body: PowerSnapshotBody) -> dict[str, Any]:
    """iOS reports previous Auto-Lock before/while keep-awake engages (logged for restore)."""
    from cumulous.device_power import record_client_auto_lock_snapshot

    return record_client_auto_lock_snapshot(
        auto_lock_seconds=body.auto_lock_seconds,
        idle_timer_disabled_before=body.idle_timer_disabled_before,
        device_id=body.device_id,
    )


@app.post("/backup/power/ack")
def api_power_ack(notification_id: str = "") -> dict[str, Any]:
    from cumulous.device_power import ack_notification

    if not notification_id:
        raise HTTPException(400, "notification_id required")
    return ack_notification(notification_id)


@app.get("/backup/power")
def api_power_policy() -> dict[str, Any]:
    from cumulous.device_power import power_policy_for_clients

    return power_policy_for_clients()


@app.get("/network/endpoints")
def api_network_endpoints() -> dict[str, Any]:
    return backup_endpoints()


@app.get("/network/wifi-hint")
def api_wifi_hint() -> dict[str, Any]:
    return enable_wifi_sync_hint()


@app.get("/photos/status")
def api_photos_status() -> dict[str, Any]:
    return library_status()


@app.get("/nextcloud/tls")
def api_nextcloud_tls() -> dict[str, Any]:
    """HTTPS posture for Nextcloud (no credentials)."""
    from cumulous.nextcloud_client import migrate_config_to_https, tls_status

    migrate_config_to_https()
    st = tls_status()
    st["ca_install"] = {
        "mac_command": "cumulous/nextcloud_stack/install_trusted_ca.command",
        "ios_profile": "/install/nextcloud-ca",
        "ca_pem": "/install/nextcloud-ca.pem",
    }
    return st


@app.get("/photos/mirror-report")
def api_photos_mirror_report() -> dict[str, Any]:
    from cumulous.install_invite import photo_mirror_status_report
    from cumulous.photo_offload import (
        harvest_progress,
        load_prefs,
        load_deletion_queue,
        load_mirror_index,
        load_device_inventory,
        library_status,
    )

    rep = photo_mirror_status_report()
    rep["prefs"] = load_prefs()
    rep["deletion_queue_pending"] = len([q for q in load_deletion_queue() if q.get("status") == "pending"])
    rep["dual_mirrored"] = sum(
        1 for it in (load_mirror_index().get("items") or {}).values() if it.get("hdd_ok") and it.get("nextcloud_ok")
    )
    lib = library_status()
    rep["file_count"] = lib.get("file_count")
    rep["device_media"] = lib.get("device_media") or load_device_inventory()
    rep["harvest"] = harvest_progress().get("harvest")
    return rep


@app.get("/photos/device-inventory")
def api_photos_device_inventory(refresh: bool = True, deep: bool = True) -> dict[str, Any]:
    """Always verify phone photo/video count when USB is available."""
    from cumulous.devices import probe_connected_device
    from cumulous.photo_offload import load_device_inventory, verify_device_media_count

    if refresh:
        probe = probe_connected_device() or {}
        return verify_device_media_count(udid=probe.get("udid") or "", deep=deep)
    inv = load_device_inventory()
    return inv if inv else {"ok": False, "error": "no_inventory_yet", "hint": "Pass refresh=true with USB connected"}


@app.post("/photos/harvest-device")
def api_photos_harvest_device(limit: int | None = None, background: bool = True) -> dict[str, Any]:
    """Full dual-mirror harvest of all AFC-reachable phone media → HDD + Nextcloud."""
    from cumulous.devices import probe_connected_device
    from cumulous.photo_offload import (
        harvest_device_media_afc,
        start_device_media_harvest,
        verify_device_media_count,
    )
    from cumulous.apple_accounts import list_accounts

    probe = probe_connected_device() or {}
    udid = probe.get("udid") or ""
    did = probe.get("imei") or probe.get("device_id") or udid
    if not udid and not did:
        return {"ok": False, "error": "no_usb_device", "message": "Plug in iPhone, unlock, Trust"}
    aid = ""
    try:
        for a in list_accounts():
            if a.get("is_ceo") or a.get("apple_id"):
                aid = a.get("apple_id") or ""
                if a.get("is_ceo"):
                    break
    except Exception:
        pass
    # Fresh count first
    inv = verify_device_media_count(udid=udid, deep=True)
    if background:
        start = start_device_media_harvest(
            device_id=str(did),
            udid=str(udid),
            apple_account_id=aid,
            limit=limit,
        )
        return {"ok": True, "inventory": inv, "harvest": start}
    res = harvest_device_media_afc(
        device_id=str(did),
        udid=str(udid),
        apple_account_id=aid,
        limit=limit,
    )
    return {"ok": bool(res.get("ok")), "inventory": inv, "harvest": res}


@app.get("/photos/harvest-progress")
def api_photos_harvest_progress() -> dict[str, Any]:
    from cumulous.photo_offload import harvest_progress

    return harvest_progress()


class MediaUploadBody(BaseModel):
    device_id: str
    apple_account_id: str = ""
    filename: str
    data_base64: str
    local_asset_id: str = ""


@app.post("/photos/mirror")
def api_photos_mirror(body: MediaUploadBody) -> dict[str, Any]:
    """Phone uploads media → dual store HDD + Nextcloud → maybe queue local delete."""
    from cumulous.photo_offload import dual_mirror_bytes

    try:
        raw = base64.b64decode(body.data_base64, validate=False)
    except Exception as e:
        raise HTTPException(400, f"bad base64: {e}") from e
    return dual_mirror_bytes(
        raw,
        device_id=body.device_id,
        rel_name=body.filename or "photo.jpg",
        apple_account_id=body.apple_account_id,
        local_asset_id=body.local_asset_id,
    )


@app.get("/photos/deletion-queue")
def api_deletion_queue(device_id: str = "") -> dict[str, Any]:
    """Cumulous iOS / automation: items safe to remove from phone (dual-verified)."""
    from cumulous.photo_offload import pending_deletions_for_device

    q = pending_deletions_for_device(device_id)
    return {
        "ok": True,
        "count": len(q),
        "items": q,
        "instruction": (
            "Delete these local originals on the device only. "
            "They remain on Mac HDD and Nextcloud for display/streaming."
        ),
    }


class DeletionAckBody(BaseModel):
    digest: str


@app.post("/photos/deletion-ack")
def api_deletion_ack(body: DeletionAckBody) -> dict[str, Any]:
    from cumulous.photo_offload import mark_deleted_on_device

    mark_deleted_on_device(body.digest)
    return {"ok": True, "digest": body.digest}


class DeviceDeleteBody(BaseModel):
    digest: str
    source: str = "mac"  # mac | ios
    execute_afc: bool = True


@app.post("/photos/device-delete")
def api_photos_device_delete(body: DeviceDeleteBody) -> dict[str, Any]:
    """Remove one dual-verified photo from the phone; vault on Mac is never deleted.

    Network clients claiming source=ios still go through protect rules; they cannot
    force AFC. Prefer on-device Cumulous app for local PHAsset delete + deletion-ack.
    """
    from cumulous.photo_offload import request_device_delete, usb_device_present

    src = (body.source or "mac").lower()
    if src not in ("mac", "ios"):
        src = "mac"
    # If USB is present, prefer mac path (AFC capable). iOS source never runs AFC.
    if src == "ios":
        return request_device_delete(
            body.digest,
            source="ios",
            require_usb=False,
            execute_afc=False,
        )
    return request_device_delete(
        body.digest,
        source="mac",
        require_usb=True,
        execute_afc=bool(body.execute_afc) and bool(usb_device_present().get("usb")),
    )


class DeviceDeleteAllBody(BaseModel):
    device_id: str = ""
    source: str = "mac"
    execute_afc: bool = True
    limit: int | None = None


@app.post("/photos/device-delete-all-freeable")
def api_photos_device_delete_all(body: DeviceDeleteAllBody) -> dict[str, Any]:
    """Remove all freeable dual-verified on-device photos (USB required from Mac)."""
    from cumulous.photo_offload import request_device_delete_all_freeable

    src = (body.source or "mac").lower()
    return request_device_delete_all_freeable(
        device_id=body.device_id or "",
        source=src,
        require_usb=(src == "mac"),
        execute_afc=bool(body.execute_afc) and src == "mac",
        limit=body.limit,
    )


class KeepOriginalsBody(BaseModel):
    enabled: bool = True


@app.post("/photos/download-and-keep-originals")
def api_photos_keep_originals(body: KeepOriginalsBody) -> dict[str, Any]:
    """After initial backup: keep new originals on phone; later harvests are add-only."""
    from cumulous.photo_offload import set_download_and_keep_originals, load_prefs

    prefs = set_download_and_keep_originals(bool(body.enabled))
    return {
        "ok": True,
        "download_and_keep_originals": prefs.get("download_and_keep_originals"),
        "free_phone_storage_after_backup": prefs.get("free_phone_storage_after_backup"),
        "add_only_vault": prefs.get("add_only_vault", True),
        "message": (
            "New photos stay on the phone and still back up to Cumulous."
            if body.enabled
            else "Free-phone-after-backup policy restored when dual-verified."
        ),
    }


@app.get("/photos/freeable")
def api_photos_freeable(device_id: str = "") -> dict[str, Any]:
    from cumulous.photo_offload import freeable_on_device, usb_device_present

    items = freeable_on_device(device_id=device_id, dual_only=True)
    return {
        "ok": True,
        "count": len(items),
        "items": items[:500],
        "usb": usb_device_present(),
    }


@app.get("/music/status")
def api_music_status() -> dict[str, Any]:
    """Music + podcast vault status (playlists left untouched on device)."""
    from cumulous.music_offload import library_status, music_harvest_progress, restore_notes_for_ceo

    prog = music_harvest_progress()
    return {
        "ok": True,
        "library": library_status(),
        "harvest": prog.get("harvest"),
        "alive": prog.get("alive"),
        "device_free": prog.get("device_free"),
        "playlists_untouched": True,
        "restore_notes": restore_notes_for_ceo(),
    }


@app.post("/music/harvest")
def api_music_harvest(limit: int | None = None, background: bool = True) -> dict[str, Any]:
    """Dual-mirror all Music + Podcasts from USB. Does not free anything; playlists only copied."""
    from cumulous.apple_accounts import list_accounts
    from cumulous.devices import probe_connected_device
    from cumulous.music_offload import harvest_music_afc, start_music_harvest

    probe = probe_connected_device() or {}
    udid = probe.get("udid") or ""
    did = probe.get("imei") or probe.get("device_id") or udid
    if not udid and not did:
        return {"ok": False, "error": "no_usb_device", "message": "Plug in iPhone, unlock, Trust"}
    aid = ""
    try:
        for a in list_accounts():
            if a.get("is_ceo") or a.get("apple_id"):
                aid = a.get("apple_id") or ""
                if a.get("is_ceo"):
                    break
    except Exception:
        pass
    if background:
        start = start_music_harvest(
            device_id=str(did),
            udid=str(udid),
            apple_account_id=aid,
            limit=limit,
        )
        return {
            "ok": True,
            "harvest": start,
            "message": "Music + podcast backup started. Playlists stay on the phone untouched.",
        }
    res = harvest_music_afc(
        device_id=str(did),
        udid=str(udid),
        apple_account_id=aid,
        limit=limit,
    )
    return {"ok": bool(res.get("ok")), "harvest": res}


@app.get("/music/harvest-progress")
def api_music_harvest_progress() -> dict[str, Any]:
    from cumulous.music_offload import music_harvest_progress

    return music_harvest_progress()


@app.get("/music/freeable")
def api_music_freeable() -> dict[str, Any]:
    """Freeable Music/Podcast items only — never playlists or local-only tracks."""
    from cumulous.music_offload import freeable_music_items, library_status
    from cumulous.photo_offload import usb_device_present

    items = freeable_music_items()
    return {
        "ok": True,
        "count": len(items),
        "bytes": sum(int(i.get("size") or 0) for i in items),
        "items": items[:500],
        "usb": usb_device_present(),
        "library": library_status(),
        "playlists_untouched": True,
        "local_only_protected": True,
    }


@app.post("/music/free")
def api_music_free(dry_run: bool = False, limit: int | None = None) -> dict[str, Any]:
    """Free Cache + cloud-eligible Downloads + podcast media after dual-verify.

    Never deletes playlists or local-only tracks. Never touches DCIM/PhotoData.
    """
    from cumulous.music_offload import free_music_on_device_usb

    res = free_music_on_device_usb(dry_run=bool(dry_run), limit=limit)
    res["playlists_untouched"] = True
    res["local_only_protected"] = True
    return res


@app.get("/music/device-free")
def api_music_device_free() -> dict[str, Any]:
    from cumulous.music_offload import device_free_bytes

    return device_free_bytes()


@app.get("/backup/categories")
def api_backup_categories(device_id: str = "", use_ai: bool = False) -> dict[str, Any]:
    """Verified backup domains + 5 intelligent subcategories each (shared by Mac/iOS/web)."""
    from cumulous.backup_categories import evaluate_categories

    return evaluate_categories(device_id=device_id or "354345290021725", use_ai=bool(use_ai))


@app.get("/backup/selectable")
def api_backup_selectable(device_id: str = "") -> dict[str, Any]:
    """Checkbox catalog: categories + subtypes + apps for selective backup/restore."""
    from cumulous.selective_backup import build_selectable_catalog

    return build_selectable_catalog(device_id=device_id or "354345290021725")


class SelectiveIdsBody(BaseModel):
    ids: list[str] = []
    device_id: str = ""
    apple_account_id: str = ""
    background: bool = True
    confirm: bool = False


@app.post("/backup/selected")
def api_backup_selected(body: SelectiveIdsBody) -> dict[str, Any]:
    """Backup only checked categories/apps."""
    from cumulous.selective_backup import backup_selected

    return backup_selected(
        list(body.ids or []),
        device_id=body.device_id or "",
        apple_account_id=body.apple_account_id or "",
        background=bool(body.background),
    )


@app.post("/backup/all")
def api_backup_all(body: SelectiveIdsBody | None = None) -> dict[str, Any]:
    """Backup All Device Data — photos + music + system."""
    from cumulous.selective_backup import backup_all_device_data

    body = body or SelectiveIdsBody()
    return backup_all_device_data(
        device_id=body.device_id or "",
        apple_account_id=body.apple_account_id or "",
    )


@app.post("/restore/selected")
def api_restore_selected(body: SelectiveIdsBody) -> dict[str, Any]:
    """Restore Selected Data — stages vault package on Mac (honest status)."""
    from cumulous.selective_backup import restore_selected

    return restore_selected(list(body.ids or []), device_id=body.device_id or "")


@app.post("/restore/all")
def api_restore_all(body: SelectiveIdsBody | None = None) -> dict[str, Any]:
    """Restore All Device Data — requires confirm=true; stages full package."""
    from cumulous.selective_backup import restore_all_device_data

    body = body or SelectiveIdsBody()
    return restore_all_device_data(device_id=body.device_id or "", confirm=bool(body.confirm))


@app.get("/backup/selective-jobs")
def api_selective_jobs(limit: int = 20) -> dict[str, Any]:
    from cumulous.selective_backup import recent_jobs

    return {"ok": True, "jobs": recent_jobs(limit=limit)}


@app.get("/storage/optimize/plan")
def api_storage_optimize_plan(
    device_id: str = "",
    mode: str = "balanced",
) -> dict[str, Any]:
    """Dry-run intelligent free-space plan (vault never touched)."""
    from cumulous.storage_optimize import plan_optimization

    m = mode if mode in ("conservative", "balanced", "aggressive") else "balanced"
    return plan_optimization(device_id=device_id, mode=m)  # type: ignore[arg-type]


class StorageOptimizeBody(BaseModel):
    device_id: str = ""
    mode: str = "balanced"
    source: str = "mac"  # mac | ios
    max_items: int | None = None
    digests: list[str] | None = None
    execute_afc: bool = True


@app.post("/storage/optimize/run")
def api_storage_optimize_run(body: StorageOptimizeBody) -> dict[str, Any]:
    """Execute storage optimization on the phone only."""
    from cumulous.storage_optimize import execute_optimization

    m = body.mode if body.mode in ("conservative", "balanced", "aggressive") else "balanced"
    return execute_optimization(
        device_id=body.device_id,
        mode=m,  # type: ignore[arg-type]
        source=body.source or "mac",
        max_items=body.max_items,
        digests=body.digests,
        execute_afc=bool(body.execute_afc),
    )


class StorageOptimizeGateBody(BaseModel):
    device_id: str = ""
    mode: str = "balanced"
    user_wants_optimize: bool | None = None
    source: str = "ios"
    execute: bool = True


@app.post("/storage/optimize/backup-gate")
def api_storage_optimize_backup_gate(body: StorageOptimizeGateBody) -> dict[str, Any]:
    """Called at the start of every backup — plan + optional execute after user answer."""
    from cumulous.storage_optimize import backup_start_storage_gate

    m = body.mode if body.mode in ("conservative", "balanced", "aggressive") else "balanced"
    return backup_start_storage_gate(
        device_id=body.device_id,
        mode=m,  # type: ignore[arg-type]
        user_wants_optimize=body.user_wants_optimize,
        source=body.source or "ios",
        execute=bool(body.execute),
    )


class FreeCategoryBody(BaseModel):
    category_id: str
    subcategory_id: str = ""
    device_id: str = ""
    source: str = "mac"  # mac | ios


@app.post("/backup/categories/free")
def api_backup_categories_free(body: FreeCategoryBody) -> dict[str, Any]:
    """Remove finished freeable data from the phone; vault on Mac is never deleted."""
    from cumulous.backup_categories import free_category_from_device, free_subcategory_from_device

    src = (body.source or "mac").lower()
    if src not in ("mac", "ios"):
        src = "mac"
    if body.subcategory_id:
        return free_subcategory_from_device(
            body.category_id,
            body.subcategory_id,
            device_id=body.device_id or "",
            source=src,
        )
    return free_category_from_device(
        body.category_id,
        device_id=body.device_id or "",
        source=src,
    )


@app.get("/photos/library")
def api_photos_library(
    device_id: str = "",
    q: str = "",
    limit: int = 120,
    offset: int = 0,
    sort: str = "date_desc",
) -> dict[str, Any]:
    """Cumulous Photos — list backed-up media (Photos.app-like feed for all devices)."""
    from cumulous.photo_library import display_policy, list_assets

    res = list_assets(device_id=device_id, query=q, limit=min(limit, 500), offset=offset, sort=sort)
    res["display"] = display_policy()
    return res


@app.get("/photos/days")
def api_photos_days(limit_days: int = 60) -> dict[str, Any]:
    from cumulous.photo_library import albums_by_day

    return {"ok": True, "days": albums_by_day(limit_days=min(limit_days, 365))}


@app.get("/photos/albums")
def api_photos_albums() -> dict[str, Any]:
    from cumulous.photo_library import albums_summary

    return {"ok": True, "albums": albums_summary()}


@app.post("/photos/scan")
def api_photos_scan(enrich: bool = True) -> dict[str, Any]:
    from cumulous.photo_library import scan_library

    return scan_library(enrich=enrich)


@app.get("/photos/thumb/{digest}")
def api_photos_thumb(digest: str) -> Response:
    from cumulous.photo_library import thumb_bytes

    data = thumb_bytes(digest)
    if not data:
        raise HTTPException(404, "thumb not found")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/photos/media/{digest}")
def api_photos_media(digest: str) -> Response:
    from cumulous.photo_library import resolve_media_path

    path = resolve_media_path(digest)
    if not path:
        raise HTTPException(404, "media not found")
    suffix = path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".mov": "video/quicktime",
        ".mp4": "video/mp4",
        ".m4v": "video/x-m4v",
    }
    return Response(
        content=path.read_bytes(),
        media_type=media_types.get(suffix, "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=3600", "Content-Disposition": f'inline; filename="{path.name}"'},
    )


@app.get("/photos/tags/{digest}")
def api_photos_tags(digest: str) -> dict[str, Any]:
    from cumulous.photo_tagging import get_tags

    tags = get_tags(digest)
    if not tags:
        raise HTTPException(404, "tags not found")
    return {"ok": True, "digest": digest, "tags": tags}


@app.post("/photos/tags/{digest}/enrich")
def api_photos_enrich(digest: str, vision: bool = True) -> dict[str, Any]:
    """Re-run deep tagging (EXIF + optional local vision model)."""
    from cumulous.photo_library import re_enrich_digest

    return re_enrich_digest(digest, run_vision=vision)


@app.get("/photos/display-policy")
def api_photos_display_policy() -> dict[str, Any]:
    from cumulous.photo_library import display_policy

    return display_policy()


@app.get("/app", response_class=HTMLResponse)
@app.get("/app/", response_class=HTMLResponse)
def app_shell() -> HTMLResponse:
    """In-app Cumulous shell — Photos library renders here (not address-bar only)."""
    index = _APP_STATIC / "index.html"
    if not index.is_file():
        raise HTTPException(404, "app shell missing")
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/app/manifest.webmanifest")
def app_manifest() -> Response:
    p = _APP_STATIC / "manifest.webmanifest"
    if not p.is_file():
        raise HTTPException(404)
    return Response(p.read_bytes(), media_type="application/manifest+json")


@app.get("/app/sw.js")
def app_sw() -> Response:
    p = _APP_STATIC / "sw.js"
    if not p.is_file():
        raise HTTPException(404)
    return Response(p.read_bytes(), media_type="application/javascript")


@app.get("/install", response_class=HTMLResponse)
def install_portal() -> str:
    """Install Cumulous — Home Screen or App Library preference + open in-app Photos."""
    from cumulous.app_update import package_version
    from cumulous.install_invite import best_app_url, write_webclip_profile
    from cumulous.network_backup import backup_endpoints

    write_webclip_profile()
    app_url = best_app_url()
    clip = "/install/webclip.mobileconfig"
    ver = package_version()
    nc = (backup_endpoints().get("nextcloud") or {})
    nc_url = nc.get("primary_phone_url") or "https://127.0.0.1:8443"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
  <meta name="apple-mobile-web-app-capable" content="yes"/>
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
  <meta name="apple-mobile-web-app-title" content="Cumulous"/>
  <link rel="apple-touch-icon" href="/install/icon.png?v={ver}"/>
  <title>Cumulous · Install v{ver}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; min-height: 100vh; background: #000; color: #f5f5f7;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
      display: flex; align-items: center; justify-content: center; padding: 24px;
    }}
    .card {{
      width: min(440px, 100%); background: #1c1c1e; border: 1px solid #2c2c2e;
      border-radius: 22px; padding: 28px 24px; text-align: center;
      box-shadow: 0 24px 80px rgba(0,0,0,.5);
    }}
    .icon {{
      width: 88px; height: 88px; border-radius: 22.5%; margin: 0 auto 18px;
      background: #000 center/cover no-repeat; border: 1px solid #3a3a3c;
    }}
    h1 {{ font-size: 1.45rem; font-weight: 600; margin: 0 0 8px; letter-spacing: -0.02em; }}
    .ver {{ display:inline-block; background:#2c2c2e; color:#0a84ff; font-size:.78rem; font-weight:600;
      padding:4px 10px; border-radius:99px; margin-bottom:12px; }}
    p {{ color: #8e8e93; font-size: .95rem; line-height: 1.45; margin: 0 0 14px; }}
    .steps {{ text-align: left; color: #d1d1d6; font-size: .88rem; line-height: 1.55; margin: 16px 0;
      background:#141414; border-radius:14px; padding:14px 16px; }}
    .steps b {{ color: #fff; }}
    .steps ol {{ margin:8px 0 0; padding-left:18px; }}
    .steps li {{ margin:6px 0; }}
    a.btn, button.btn {{
      display: block; width: 100%; color: #fff; text-decoration: none;
      font-weight: 600; border-radius: 14px; padding: 14px 16px; margin: 10px 0; font-size: 1rem;
      cursor: pointer; text-align: center;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.38) 0%, rgba(255,255,255,0.12) 32%, rgba(255,255,255,0) 55%),
        linear-gradient(180deg, #1a8fff 0%, #007AFF 48%, #0062cc 100%);
      border: 1px solid rgba(255,255,255,0.28);
      box-shadow: 0 1px 0 rgba(255,255,255,0.4) inset, 0 6px 18px rgba(0,122,255,0.32);
    }}
    a.btn.secondary, button.btn.secondary {{
      background: #2c2c2e;
      border: 1px solid #3a3a3c;
      box-shadow: none;
    }}
    .row {{ display: flex; gap: 10px; margin-top: 4px; }}
    .row a, .row button {{ flex: 1; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon" style="background-image:url('/install/icon.png?v={ver}')"></div>
    <div class="ver">v{ver} · Delphi Technologies</div>
    <h1>Install Cumulous</h1>
    <p>Full-screen app: <b>Photos open inside Cumulous</b>. Version is recorded on this device whenever you install or open the app.</p>
    <div class="steps">
      <b>Install steps (iPhone · Safari)</b>
      <ol>
        <li>Tap <b>Add to Home Screen (profile)</b> below</li>
        <li>Tap <b>Allow</b>, then open <b>Settings → Profile Downloaded → Install</b></li>
        <li>Enter your passcode if asked → <b>Install</b></li>
        <li>Open the new <b>Cumulous</b> icon on your Home Screen</li>
        <li>Stay on Wi‑Fi (or Tailscale) so the Mac Mini vault can sync</li>
      </ol>
      Or: <b>Open now</b> for full-screen Photos without the profile.
    </div>
    <a class="btn" href="{clip}">Add to Home Screen (profile)</a>
    <a class="btn secondary" id="openApp" href="/app/?v={ver}">Open Cumulous App (Photos)</a>
    <div class="row">
      <a class="btn secondary" href="/install/respond?accepted=1&amp;preference=homescreen">Home Screen</a>
      <a class="btn secondary" href="/install/respond?accepted=1&amp;preference=app_section">App Library</a>
    </div>
    <a class="btn secondary" href="/install/respond?accepted=0&amp;preference=declined">Not now</a>
    <a class="btn secondary" href="/install/nextcloud-ca">Trust Nextcloud Certificate</a>
    <p style="font-size:.8rem;margin-top:12px">Optional Nextcloud: <code style="color:#fff">{nc_url}</code></p>
  </div>
  <script>
    (function() {{
      document.getElementById('openApp').href = '/app/?v={ver}';
      // Register this device version on install-screen open
      var did = localStorage.getItem('cumulous_device_id') || ('web-' + (navigator.userAgent||'').slice(0,24).replace(/\\W/g,'_'));
      try {{ localStorage.setItem('cumulous_device_id', did); }} catch(e) {{}}
      fetch('/install/register', {{
        method: 'POST',
        headers: {{'Content-Type':'application/json'}},
        body: JSON.stringify({{
          device_id: did,
          version: '{ver}',
          platform: 'ios_web',
          source: 'install_screen',
          display_name: 'iPhone Safari'
        }})
      }}).catch(function(){{}});
    }})();
  </script>
</body>
</html>
"""


@app.get("/install/nextcloud-ca")
def install_nextcloud_ca_profile() -> Response:
    """iOS/macOS configuration profile that installs the Cumulous Nextcloud CA (trusted cert)."""
    from pathlib import Path

    p = Path(__file__).resolve().parent / "assets" / "Cumulous-Nextcloud-CA.mobileconfig"
    if not p.is_file():
        raise HTTPException(404, "CA profile missing — re-run issue_certs.sh")
    return Response(
        content=p.read_bytes(),
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": 'attachment; filename="Cumulous-Nextcloud-CA.mobileconfig"'},
    )


@app.get("/install/nextcloud-ca.pem")
def install_nextcloud_ca_pem() -> Response:
    """Download Cumulous Nextcloud CA PEM (for manual trust / other devices)."""
    from pathlib import Path

    for p in (
        Path(__file__).resolve().parent / "nextcloud_stack" / "certs" / "ca.pem",
        Path.home() / ".cumulous" / "nextcloud_ca.pem",
    ):
        if p.is_file():
            return Response(
                content=p.read_bytes(),
                media_type="application/x-pem-file",
                headers={"Content-Disposition": 'attachment; filename="cumulous-nextcloud-ca.pem"'},
            )
    raise HTTPException(404, "CA not found")


@app.get("/install/icon.png")
def install_icon(v: str = "") -> Response:
    """Latest Cumulous icon (query ?v= busts Home Screen / browser cache)."""
    from pathlib import Path

    p = Path(__file__).resolve().parent / "assets" / "icons" / "AppIcon-1024.png"
    if not p.is_file():
        p = Path(__file__).resolve().parent / "assets" / "icons" / "cumulous_ios_icon.png"
    if not p.is_file():
        raise HTTPException(404, "icon missing")
    data = p.read_bytes()
    # weak etag from content
    import hashlib

    etag = hashlib.sha256(data).hexdigest()[:16]
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "no-cache, must-revalidate",
            "ETag": f'"{etag}"',
            "X-Cumulous-Icon-Version": v or etag,
        },
    )


@app.get("/install/webclip.mobileconfig")
def install_webclip() -> Response:
    from cumulous.install_invite import write_webclip_profile

    path = write_webclip_profile()
    data = path.read_bytes()
    return Response(
        content=data,
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": "attachment; filename=Cumulous-HomeScreen.mobileconfig"},
    )


@app.get("/install/respond")
def install_respond(
    accepted: int = 0,
    invite_id: str = "",
    preference: str = "",
    device_id: str = "",
) -> HTMLResponse:
    from cumulous.app_update import package_version
    from cumulous.install_invite import load_invites, record_response

    ver = package_version()
    if invite_id:
        record_response(
            invite_id,
            accepted=bool(accepted),
            device_id=device_id,
            preference=preference,
            version=ver,
        )
    else:
        data = load_invites()
        for inv in reversed(data.get("invites") or []):
            if inv.get("status") == "pending":
                record_response(
                    inv["invite_id"],
                    accepted=bool(accepted),
                    device_id=device_id or inv.get("device_id") or "",
                    preference=preference,
                    version=ver,
                )
                break
    if accepted:
        pref_label = "Home Screen" if preference == "homescreen" else ("App Library" if preference == "app_section" else "Installed")
        msg = f"Cumulous v{ver} · {pref_label} saved. Opening Photos app…"
        next_link = f"/app/?v={ver}"
    else:
        msg = "No problem — you can add Cumulous later anytime."
        next_link = "/install"
    return HTMLResponse(
        f"""<!DOCTYPE html><html><head><meta http-equiv="refresh" content="{2 if accepted else 0};url={next_link}"/></head>
        <body style="background:#000;color:#f5f5f7;font-family:-apple-system,sans-serif;
        display:flex;align-items:center;justify-content:center;min-height:100vh">
        <div style="text-align:center;max-width:320px"><h2>{"You're in" if accepted else "Declined"}</h2>
        <p style="color:#8e8e93">{msg}</p>
        <a href="{next_link}" style="color:#0a84ff">{"Open Photos" if accepted else "Back"}</a></div></body></html>"""
    )


@app.post("/install/push-connected")
def api_push_connected(force: bool = True, wait_sec: float = 45) -> dict[str, Any]:
    """Mac button: push Cumulous install to the USB-connected iPhone.

    Waits briefly for usbmux so a just-plugged cable is picked up.
    """
    from cumulous.install_invite import push_install_to_usb_device

    return push_install_to_usb_device(force=force, wait_sec=wait_sec)


@app.post("/install/invite-account")
def api_invite_account(apple_account_id: str = "") -> dict[str, Any]:
    from cumulous.install_invite import invite_all_apple_account_devices
    from cumulous.apple_accounts import list_accounts

    aid = apple_account_id
    if not aid:
        accs = list_accounts()
        for a in accs:
            if a.get("is_ceo"):
                aid = a["apple_id"]
                break
        if not aid and accs:
            aid = accs[0]["apple_id"]
    return invite_all_apple_account_devices(aid)


@app.post("/install/push-all")
def api_install_push_all(force: bool = True, apple_account_id: str = "") -> dict[str, Any]:
    """Push install-screen notification to all registered iPhones + Mac."""
    from cumulous.install_invite import push_install_to_all_devices

    return push_install_to_all_devices(force=force, apple_account_id=apple_account_id)


@app.get("/install/live")
def api_install_live(device_id: str = "") -> dict[str, Any]:
    """Phones poll this for live install push → open /install."""
    from cumulous.install_invite import active_install_pushes_for_device

    pushes = active_install_pushes_for_device(device_id)
    return {
        "ok": True,
        "count": len(pushes),
        "pushes": pushes,
        "latest": pushes[0] if pushes else None,
    }


class InstallRegisterBody(BaseModel):
    device_id: str = ""
    version: str = ""
    platform: str = "ios"
    source: str = "app_launch"
    display_name: str = ""
    preference: str = ""


@app.post("/install/register")
def api_install_register(body: InstallRegisterBody) -> dict[str, Any]:
    """Persistently record installed Cumulous version on a device (every install/launch)."""
    from cumulous.app_update import package_version, record_device_install

    rec = record_device_install(
        device_id=body.device_id or "unknown",
        version=body.version or package_version(),
        platform=body.platform or "ios",
        source=body.source or "app_launch",
        display_name=body.display_name,
        preference=body.preference,
    )
    return {
        "ok": True,
        "device": rec,
        "package_version": package_version(),
        "up_to_date": rec.get("up_to_date"),
    }


@app.get("/install/devices")
def api_install_devices() -> dict[str, Any]:
    """CEO/Mac view: which devices have which Cumulous version."""
    from cumulous.app_update import list_device_installs, package_version

    rows = list_device_installs()
    return {
        "ok": True,
        "package_version": package_version(),
        "count": len(rows),
        "devices": rows,
    }


@app.post("/install/ack")
def api_install_ack(push_id: str = "") -> dict[str, Any]:
    from cumulous.install_invite import ack_install_push

    if not push_id:
        return {"ok": False, "error": "push_id required"}
    return ack_install_push(push_id)


@app.get("/agents")
def agents() -> dict[str, Any]:
    return {"roster": roster_count(), "rows": dashboard_rows()}


@app.post("/auth/bearaccount")
def api_create_bear(body: BearBody) -> dict[str, Any]:
    try:
        return create_bearaccount(body.username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/auth/user")
def api_create_user(body: UserBody) -> dict[str, Any]:
    try:
        return create_user(
            body.username,
            body.password,
            apple_id_hint=body.apple_id_hint,
            device_ids=body.device_ids,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/auth/login")
def api_login(body: LoginBody) -> dict[str, Any]:
    return authenticate(body.username, body.password, totp_code=body.totp_code)


@app.post("/challenge/spawn")
def api_spawn(body: ChallengeBody) -> dict[str, Any]:
    # Prefer registry resolution (user ∪ CEOOVERRIDE). Explicit lists only if provided.
    if body.user_device_ids or body.ceo_override_device_ids:
        return spawn_challenge(
            purpose=body.purpose,
            requesting_user_id=body.requesting_user_id,
            user_device_ids=body.user_device_ids or devices_for_user(body.requesting_user_id),
            ceo_override_device_ids=body.ceo_override_device_ids or ceo_override_device_ids(),
        )
    return spawn_challenge_for_user(
        purpose=body.purpose,
        requesting_user_id=body.requesting_user_id,
    )


@app.post("/challenge/verify")
def api_verify(body: VerifyChallengeBody) -> dict[str, Any]:
    ok = verify_challenge(body.code, purpose=body.purpose)
    return {"ok": ok}


@app.get("/challenge/live")
def api_challenge_live(
    device_id: str = "",
    apple_account_id: str = "",
) -> dict[str, Any]:
    """Phones poll this to show the verification code live (Apple-style fan-out).

    Returns code + map for the requesting device. Any registered device on the
    Apple Account receives the payload (not Mac-only).
    """
    from cumulous.challenge_push import active_codes_for_device, latest_active_code

    codes = active_codes_for_device(device_id, apple_account_id=apple_account_id)
    if not codes:
        latest = latest_active_code(
            device_id=device_id, apple_account_id=apple_account_id
        )
        codes = [latest] if latest else []
    return {
        "ok": True,
        "count": len(codes),
        "codes": codes,
        "latest": codes[0] if codes else None,
    }


@app.get("/challenge/pending")
def api_challenge_pending(
    device_id: str = "",
    apple_account_id: str = "",
) -> dict[str, Any]:
    """Alias for /challenge/live — Cumulous app / app shell."""
    return api_challenge_live(device_id=device_id, apple_account_id=apple_account_id)


class LocationBody(BaseModel):
    device_id: str
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    label: str = ""


@app.post("/challenge/location")
def api_challenge_location(body: LocationBody) -> dict[str, Any]:
    """iOS reports GPS so challenge maps show the correct requesting-device location."""
    from cumulous.device_location import record_device_location

    return record_device_location(
        body.device_id,
        latitude=body.latitude,
        longitude=body.longitude,
        accuracy_m=body.accuracy_m,
        source="ios_core_location",
        label=body.label or "",
    )


@app.get("/challenge/display")
def api_challenge_display() -> Any:
    """Full-screen Apple-style Confirm 4-Digit Code page for iPhone Safari / shell."""
    from fastapi.responses import HTMLResponse

    from cumulous.challenge_push import latest_active_code

    live = latest_active_code() or {}
    code = str(live.get("code") or "————")
    digits = "".join(c for c in code if c.isdigit())[:4].zfill(4) if code != "————" else "····"
    boxes = "".join(
        f'<div class="box">{d}</div>' for d in (digits if code != "————" else "····")
    )
    loc = live.get("location") or {}
    place = live.get("display_place") or loc.get("display_place") or "Approximate location"
    map_url = live.get("map_url") or loc.get("map_url") or ""
    map_img = (
        f'<img class="map" src="{map_url}" alt="map" referrerpolicy="no-referrer"/>'
        if map_url
        else '<div class="map empty">Map loading…</div>'
    )
    ttl = int(live.get("seconds_left") or 0)
    mins = max(1, ttl // 60) if ttl else 30
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<title>Confirm 4-Digit Code</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; background:#000; color:#fff;
    font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif;
    display:flex; align-items:center; justify-content:center; padding:20px; }}
  .card {{ width:min(280px,92vw); background:#2c2c2e; border-radius:18px;
    border:1px solid rgba(201,162,39,.3); padding:18px 16px 16px; text-align:center;
    box-shadow:0 24px 60px rgba(0,0,0,.55); }}
  h1 {{ font-size:15px; font-weight:600; margin:0 0 4px; letter-spacing:-.01em; }}
  .sub {{ font-size:11px; color:#c7c7cc; margin-bottom:14px; }}
  .boxes {{ display:flex; gap:8px; justify-content:center; margin:10px 0 12px; }}
  .box {{ width:42px; height:50px; border-radius:8px; background:#1c1c1e;
    border:1px solid rgba(255,255,255,.14); display:flex; align-items:center; justify-content:center;
    font-size:24px; font-weight:600; font-variant-numeric:tabular-nums; }}
  .place {{ font-size:12px; color:#e8e8ed; margin:6px 0 8px; font-weight:500; }}
  .map-wrap {{ width:100%; height:120px; border-radius:10px; overflow:hidden;
    border:1px solid rgba(201,162,39,.25); background:#1a1a1c; }}
  .map {{ width:100%; height:120px; object-fit:cover; display:block; }}
  .map.empty {{ display:flex; align-items:center; justify-content:center; color:#8e8e93; font-size:12px; }}
  .ttl {{ font-size:11px; color:#a1a1a6; margin-top:10px; }}
  .actions {{ display:flex; justify-content:flex-end; margin-top:12px; }}
  /* Apple systemBlue #007AFF */
  .btn-input {{
    background:#007AFF; color:#fff; border:none; border-radius:12px;
    font-weight:600; font-size:15px; padding:10px 18px; cursor:pointer;
    font-family:inherit;
  }}
  .btn-input:active {{ filter:brightness(0.92); }}
  .entry {{ display:none; margin-top:12px; }}
  .entry input {{
    width:120px; font-size:28px; letter-spacing:0.35em; text-align:center;
    font-weight:600; border-radius:10px; border:1px solid rgba(255,255,255,.15);
    background:#1c1c1e; color:#fff; padding:8px; font-family:inherit;
  }}
</style>
<meta http-equiv="refresh" content="20"/>
</head><body>
<div class="card" id="delivery">
  <h1>Confirm 4-Digit Code</h1>
  <div class="sub">Cumulous · one code · all your devices</div>
  <div class="boxes">{boxes}</div>
  <div class="place">{place}</div>
  <div class="map-wrap">{map_img}</div>
  <div class="ttl">Valid about {mins} min · one code only</div>
  <div class="actions">
    <button type="button" class="btn-input" id="btnInput">Input Code</button>
  </div>
  <div class="entry" id="entry">
    <input id="pin" maxlength="4" inputmode="numeric" pattern="[0-9]*" placeholder="••••" autocomplete="one-time-code"/>
    <div class="actions" style="margin-top:10px">
      <button type="button" class="btn-input" id="btnVerify">Verify</button>
    </div>
  </div>
</div>
<script>
  document.getElementById('btnInput').onclick = () => {{
    document.getElementById('entry').style.display = 'block';
    document.getElementById('pin').focus();
  }};
  document.getElementById('btnVerify').onclick = async () => {{
    const code = document.getElementById('pin').value.replace(/\\D/g,'').slice(0,4);
    if (code.length !== 4) return;
    try {{
      const r = await fetch('/challenge/verify', {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{code, purpose:'confirm_user'}})
      }});
      const j = await r.json();
      alert(j.ok ? 'Verified' : 'Code not accepted');
    }} catch(e) {{ alert('Could not verify'); }}
  }};
  // Ensure map image fully loads; retry once on error
  const img = document.querySelector('.map');
  if (img && img.tagName === 'IMG') {{
    img.onerror = () => {{ img.src = img.src.split('&cb=')[0] + '&cb=' + Date.now(); }};
  }}
</script>
</body></html>"""
    return HTMLResponse(html)


@app.post("/backup/run")
@app.post("/backup/upload")
def api_backup(body: BackupBody) -> dict[str, Any]:
    """Accept progressive backup payloads over Wi‑Fi or cellular (Tailscale)."""
    files: dict[str, bytes] = {}
    for path, content in body.files.items():
        if body.encoding == "base64":
            try:
                files[path] = base64.b64decode(content, validate=False)
            except (binascii.Error, ValueError):
                files[path] = content.encode("utf-8", errors="replace")
        else:
            files[path] = content.encode("utf-8")
    t0 = fingerprint_files(files)
    result = create_generation(
        body.device_id,
        files,
        body.password,
        categories=body.categories,
        mode=body.mode,
    )
    result["transport"] = body.transport
    result["apple_account_id"] = body.apple_account_id
    if result.get("status") == "ok":
        report = verify_against_generation(body.device_id, result["head"], t0)
        result["verification"] = report
        if report["status"] == "failed":
            result["warning"] = "verification_failed_head_not_trusted_without_ack"
        # Optional: copy photo-like paths into HDD photo library
        try:
            from cumulous.photo_offload import device_album_dir, load_prefs

            prefs = load_prefs()
            if prefs.get("host_originals_on_hdd"):
                album = device_album_dir(body.device_id, body.apple_account_id)
                n = 0
                for rel, data in files.items():
                    low = rel.lower()
                    if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".heic", ".heif", ".mov", ".mp4")):
                        dest = album / PathSafe(rel)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(data)
                        n += 1
                result["photos_mirrored_to_hdd"] = n
                result["photo_album"] = str(album)
        except Exception as e:
            result["photo_mirror_error"] = str(e)[:200]
    return result


def PathSafe(rel: str):
    from pathlib import Path

    # prevent path traversal
    p = Path(rel.replace("\\", "/"))
    parts = [x for x in p.parts if x not in ("", ".", "..")]
    return Path(*parts) if parts else Path("file.bin")


@app.get("/totp/status")
def totp_status() -> dict[str, Any]:
    sec = load_secret()
    return {"enrolled": bool(sec), "uri": provisioning_uri(sec) if sec else None}


def main() -> None:
    import os

    import uvicorn

    # 0.0.0.0 so iPhone can reach Mac Mini over Wi‑Fi / Tailscale cellular
    host = os.environ.get("CUMULOUS_API_HOST", "0.0.0.0")
    port = int(os.environ.get("CUMULOUS_API_PORT", "8765"))
    uvicorn.run("cumulous.fastapi_bridge:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
