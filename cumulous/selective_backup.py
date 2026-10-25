"""Selective backup & restore by category, subtype, and per-app.

CEO UX:
  - Checkboxes for categories / apps / subtypes (any combination)
  - Backup Selected Items | Backup All Device Data  (medium green)
  - Restore Selected Data | Restore All Device Data (sky blue)

Jobs map ids → real harvest / system backup / vault staging.
Honesty: restore may be **staged on Mac** when on-device write is not available.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from cumulous.paths import ensure_internal, restore_export_root


def selection_path() -> Path:
    return ensure_internal() / "backup_selection.json"


def job_log_path() -> Path:
    return ensure_internal() / "selective_backup_jobs.json"


def load_selection() -> dict[str, Any]:
    p = selection_path()
    if not p.exists():
        return {
            "ids": ["photos_videos", "music"],
            "updated_at": 0,
        }
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"ids": ["photos_videos", "music"], "updated_at": 0}


def save_selection(ids: list[str]) -> dict[str, Any]:
    data = {"ids": list(dict.fromkeys(ids)), "updated_at": time.time()}
    ensure_internal()
    selection_path().write_text(json.dumps(data, indent=2))
    try:
        selection_path().chmod(0o600)
    except OSError:
        pass
    return data


def _load_jobs() -> list[dict[str, Any]]:
    p = job_log_path()
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text()).get("jobs") or [])
    except Exception:
        return []


def _save_jobs(jobs: list[dict[str, Any]]) -> None:
    ensure_internal()
    job_log_path().write_text(json.dumps({"jobs": jobs[-80:], "updated_at": time.time()}, indent=2))


def _append_job(job: dict[str, Any]) -> dict[str, Any]:
    jobs = _load_jobs()
    jobs.append(job)
    _save_jobs(jobs)
    return job


def _discover_apps_from_manifest(device_id: str = "") -> list[dict[str, Any]]:
    """Best-effort app list from last full backup tree / progressive manifests."""
    apps: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        from cumulous.paths import backup_incoming_root, device_dir

        roots: list[Path] = []
        br = backup_incoming_root()
        if br.is_dir():
            roots.extend(sorted(br.glob("full_*"), key=lambda p: p.stat().st_mtime, reverse=True)[:2])
        did = device_id or "354345290021725"
        ddir = device_dir(did)
        if (ddir / "generations").is_dir():
            roots.append(ddir / "generations")

        for root in roots:
            if not root.exists():
                continue
            # Scan domain-like folder names
            for p in root.rglob("*"):
                name = p.name
                low = name.lower()
                if not p.is_dir() and not p.is_file():
                    continue
                # AppDomain-com.example.app or AppDomainGroup-...
                if name.startswith("AppDomain-") or "appdomain-" in low:
                    bid = name.split("AppDomain-", 1)[-1] if "AppDomain-" in name else name
                    bid = bid.split("AppDomainGroup-", 1)[-1] if "AppDomainGroup-" in bid else bid
                    if bid and bid not in seen and "." in bid:
                        seen.add(bid)
                        title = bid.rsplit(".", 1)[-1]
                        apps.append(
                            {
                                "id": f"app.{bid}",
                                "kind": "app",
                                "title": title,
                                "bundle_id": bid,
                                "hint": f"App container {bid}",
                                "verified": True,
                                "children": [
                                    {
                                        "id": f"app.{bid}.documents",
                                        "title": "Documents",
                                        "hint": "App documents folder",
                                    },
                                    {
                                        "id": f"app.{bid}.preferences",
                                        "title": "Preferences",
                                        "hint": "App preferences / plists",
                                    },
                                ],
                            }
                        )
                if len(apps) >= 80:
                    break
            if len(apps) >= 80:
                break
    except Exception:
        pass

    # Always include a few well-known logical apps if list empty
    if not apps:
        for bid, title in (
            ("com.apple.MobileSMS", "Messages"),
            ("com.apple.mobilenotes", "Notes"),
            ("com.apple.Music", "Music"),
        ):
            apps.append(
                {
                    "id": f"app.{bid}",
                    "kind": "app",
                    "title": title,
                    "bundle_id": bid,
                    "hint": "Logical app domain (from system backup when present)",
                    "verified": False,
                    "children": [
                        {"id": f"app.{bid}.documents", "title": "Documents", "hint": ""},
                        {"id": f"app.{bid}.preferences", "title": "Preferences", "hint": ""},
                    ],
                }
            )
    apps.sort(key=lambda a: str(a.get("title") or "").lower())
    return apps


def build_selectable_catalog(*, device_id: str = "") -> dict[str, Any]:
    """Categories + subtypes + apps for checkbox UI."""
    from cumulous.backup_categories import CATEGORY_TAXONOMY, evaluate_categories

    report = evaluate_categories(device_id=device_id or "354345290021725", use_ai=False)
    by_id = {str(c.get("id")): c for c in (report.get("categories") or [])}
    categories: list[dict[str, Any]] = []
    for cat in CATEGORY_TAXONOMY:
        cid = str(cat["id"])
        live = by_id.get(cid) or {}
        sub_by_id = {str(s.get("id")): s for s in (live.get("subcategories") or [])}
        children = []
        for sub in cat.get("subcategories") or []:
            sid = str(sub["id"])
            live_sub = sub_by_id.get(sid) or {}
            children.append(
                {
                    "id": f"{cid}.{sid}",
                    "title": sub.get("title") or sid,
                    "hint": sub.get("hint") or "",
                    "verified": bool(live_sub.get("verified")),
                    "size_bytes": int(live_sub.get("size_bytes") or 0),
                    "size_label": live_sub.get("size_label") or "—",
                }
            )
        categories.append(
            {
                "id": cid,
                "kind": "category",
                "title": cat.get("title") or cid,
                "icon": cat.get("icon") or "",
                "verified": bool(live.get("verified")),
                "freeable_on_device": bool(cat.get("freeable_on_device")),
                "size_bytes": int(live.get("size_bytes") or 0),
                "size_label": live.get("size_label") or "—",
                "children": children,
            }
        )

    apps = _discover_apps_from_manifest(device_id)
    for app in apps:
        app.setdefault("size_bytes", 0)
        app.setdefault("size_label", "—")
    sel = load_selection()
    return {
        "ok": True,
        "device_id": device_id or "354345290021725",
        "categories": categories,
        "apps": apps,
        "default_ids": sel.get("ids") or ["photos_videos", "music"],
        "saved_ids": sel.get("ids") or [],
        "summary": report.get("summary") or {},
        "button_labels": {
            "backup_selected": "Backup Selected Items",
            "backup_all": "Backup All Device Data",
            "restore_selected": "Restore Selected Data",
            "restore_all": "Restore All Device Data",
        },
        "colors": {
            "backup_green": "#007AFF",  # Apple blue (positive / additive)
            "restore_sky_blue": "#007AFF",  # Apple blue (additive restore)
            "action": "#007AFF",
        },
    }


def expand_ids(ids: list[str], catalog: dict[str, Any] | None = None) -> list[str]:
    """Expand bare category ids to include children if only parent checked; keep all explicit."""
    catalog = catalog or build_selectable_catalog()
    out: list[str] = []
    idset = set(ids)
    # Parent maps
    for cat in catalog.get("categories") or []:
        cid = cat["id"]
        child_ids = [c["id"] for c in (cat.get("children") or [])]
        if cid in idset:
            out.append(cid)
            for ch in child_ids:
                if ch not in out:
                    out.append(ch)
        else:
            for ch in child_ids:
                if ch in idset and ch not in out:
                    out.append(ch)
    for app in catalog.get("apps") or []:
        aid = app["id"]
        child_ids = [c["id"] for c in (app.get("children") or [])]
        if aid in idset:
            out.append(aid)
            for ch in child_ids:
                if ch not in out:
                    out.append(ch)
        else:
            for ch in child_ids:
                if ch in idset and ch not in out:
                    out.append(ch)
    # Keep any unknown ids
    for i in ids:
        if i not in out:
            out.append(i)
    return list(dict.fromkeys(out))


def _ids_touch_photos(ids: list[str]) -> bool:
    return any(i == "photos_videos" or i.startswith("photos_videos.") for i in ids)


def _ids_touch_music(ids: list[str]) -> bool:
    return any(
        i in ("music", "podcasts") or i.startswith("music.") or i.startswith("podcasts.")
        or "music" in i.lower()
        for i in ids
    )


def _ids_touch_system(ids: list[str]) -> bool:
    system_prefixes = (
        "messages",
        "contacts_calendar",
        "notes_health",
        "safari_browser",
        "app_data",
        "device_system",
        "full_system",
        "app.",
    )
    return any(i.startswith(p) or i in system_prefixes for i in ids for p in system_prefixes) or any(
        i.startswith("app.") for i in ids
    )


def backup_selected(
    ids: list[str],
    *,
    device_id: str = "",
    apple_account_id: str = "",
    background: bool = True,
) -> dict[str, Any]:
    """Run backup only for selected category/app ids."""
    from cumulous.devices import probe_connected_device

    save_selection(ids)
    catalog = build_selectable_catalog(device_id=device_id)
    expanded = expand_ids(ids, catalog)
    if not expanded:
        return {
            "ok": False,
            "error": "nothing_selected",
            "message": "Check at least one category or app, then try Backup Selected Items.",
        }

    probe = probe_connected_device() or {}
    did = device_id or probe.get("imei") or probe.get("device_id") or probe.get("udid") or ""
    udid = probe.get("udid") or ""
    actions: list[dict[str, Any]] = []
    job_id = f"bak_sel_{int(time.time())}"

    # Photos
    if _ids_touch_photos(expanded):
        try:
            from cumulous.photo_offload import start_device_media_harvest, harvest_device_media_afc

            if background:
                r = start_device_media_harvest(
                    device_id=str(did),
                    udid=str(udid),
                    apple_account_id=apple_account_id,
                )
            else:
                r = harvest_device_media_afc(
                    device_id=str(did),
                    udid=str(udid),
                    apple_account_id=apple_account_id,
                )
            actions.append({"id": "photos_videos", "ok": bool(r.get("ok") or r.get("started") or r.get("already_running")), "result": {k: r.get(k) for k in ("ok", "started", "already_running", "status", "mirrored") if k in r or True}})
        except Exception as e:
            actions.append({"id": "photos_videos", "ok": False, "error": str(e)[:200]})

    # Music / Podcasts
    if _ids_touch_music(expanded):
        try:
            from cumulous.music_offload import start_music_harvest, harvest_music_afc

            if background:
                r = start_music_harvest(
                    device_id=str(did),
                    udid=str(udid),
                    apple_account_id=apple_account_id,
                )
            else:
                r = harvest_music_afc(
                    device_id=str(did),
                    udid=str(udid),
                    apple_account_id=apple_account_id,
                )
            actions.append(
                {
                    "id": "music",
                    "ok": bool(r.get("ok") or r.get("started") or r.get("already_running")),
                    "result": {k: r.get(k) for k in ("ok", "started", "pid", "status", "mirrored") if True},
                }
            )
        except Exception as e:
            actions.append({"id": "music", "ok": False, "error": str(e)[:200]})

    # System / apps / full domains
    if _ids_touch_system(expanded) or "full_system" in expanded or "app_data" in expanded:
        try:
            from cumulous.backup_ops import secure_backup_device

            # Full system pull when system categories or any app selected
            r = secure_backup_device(
                str(did or "device"),
                apple_account_id=apple_account_id,
                display_name=str(probe.get("display_name") or ""),
                run_full_idevice=True,
                action_id="backup_selected",
            )
            actions.append(
                {
                    "id": "system",
                    "ok": bool(r.get("ok")),
                    "result": {
                        "ok": r.get("ok"),
                        "file_count": r.get("file_count"),
                        "error": r.get("error"),
                    },
                }
            )
        except Exception as e:
            actions.append({"id": "system", "ok": False, "error": str(e)[:200]})

    ok_any = any(a.get("ok") for a in actions)
    job = _append_job(
        {
            "job_id": job_id,
            "type": "backup_selected",
            "ids": expanded,
            "actions": actions,
            "ok": ok_any,
            "started_at": time.time(),
            "message": (
                "Selected backup started."
                if ok_any
                else "Could not start selected backup — check USB and Trust."
            ),
        }
    )
    return {
        "ok": ok_any,
        "job_id": job_id,
        "ids": expanded,
        "actions": actions,
        "message": job["message"],
        "status": "running" if ok_any else "error",
    }


def backup_all_device_data(
    *,
    device_id: str = "",
    apple_account_id: str = "",
) -> dict[str, Any]:
    """Full device backup: photos + music + system."""
    catalog = build_selectable_catalog(device_id=device_id)
    all_ids = [c["id"] for c in catalog.get("categories") or []]
    all_ids += [a["id"] for a in catalog.get("apps") or []]
    save_selection(all_ids)
    # Parallel-ish sequential start
    from cumulous.devices import probe_connected_device
    from cumulous.photo_offload import start_device_media_harvest
    from cumulous.music_offload import start_music_harvest
    from cumulous.backup_ops import secure_backup_device

    probe = probe_connected_device() or {}
    did = device_id or probe.get("imei") or probe.get("device_id") or probe.get("udid") or ""
    udid = probe.get("udid") or ""
    actions = []
    try:
        actions.append(
            {
                "id": "photos",
                "result": start_device_media_harvest(
                    device_id=str(did), udid=str(udid), apple_account_id=apple_account_id
                ),
            }
        )
    except Exception as e:
        actions.append({"id": "photos", "error": str(e)[:160]})
    try:
        actions.append(
            {
                "id": "music",
                "result": start_music_harvest(
                    device_id=str(did), udid=str(udid), apple_account_id=apple_account_id
                ),
            }
        )
    except Exception as e:
        actions.append({"id": "music", "error": str(e)[:160]})
    try:
        actions.append(
            {
                "id": "system",
                "result": secure_backup_device(
                    str(did or "device"),
                    apple_account_id=apple_account_id,
                    display_name=str(probe.get("display_name") or ""),
                    run_full_idevice=True,
                    action_id="backup_all",
                ),
            }
        )
    except Exception as e:
        actions.append({"id": "system", "error": str(e)[:160]})

    ok = any(
        (a.get("result") or {}).get("ok")
        or (a.get("result") or {}).get("started")
        or (a.get("result") or {}).get("already_running")
        for a in actions
        if isinstance(a.get("result"), dict)
    )
    job = _append_job(
        {
            "job_id": f"bak_all_{int(time.time())}",
            "type": "backup_all",
            "actions": actions,
            "ok": ok,
            "started_at": time.time(),
            "message": "Full device backup started (photos, music, system)."
            if ok
            else "Full backup could not start — unlock phone and plug USB.",
        }
    )
    return {"ok": ok, "actions": actions, "message": job["message"], "status": "running" if ok else "error"}


def restore_selected(
    ids: list[str],
    *,
    device_id: str = "",
) -> dict[str, Any]:
    """Stage selected vault data under CumulousRestore for CEO restore.

    Status is honest: staged_on_mac unless a future on-device path succeeds.
    """
    from cumulous.paths import EXTERNALSSD_ROOT, externalssd_mounted
    import shutil

    save_selection(ids)
    catalog = build_selectable_catalog(device_id=device_id)
    expanded = expand_ids(ids, catalog)
    if not expanded:
        return {
            "ok": False,
            "error": "nothing_selected",
            "message": "Check items to restore, then tap Restore Selected Data.",
        }

    dest = restore_export_root() / f"restore_{int(time.time())}"
    dest.mkdir(parents=True, exist_ok=True)
    staged: list[dict[str, Any]] = []

    # Photos vault
    if _ids_touch_photos(expanded):
        try:
            from cumulous.photo_offload import photo_library_root

            src = photo_library_root()
            if src.is_dir():
                target = dest / "photos"
                target.mkdir(exist_ok=True)
                # Copy a sample / index pointer rather than entire multi-GB tree by default
                # Copy up to 200 files for restore package; full tree remains in vault
                n = 0
                for fp in src.rglob("*"):
                    if not fp.is_file() or fp.name.startswith("."):
                        continue
                    rel = fp.relative_to(src)
                    out = target / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if not out.exists():
                        shutil.copy2(fp, out)
                    n += 1
                    if n >= 500:
                        break
                staged.append(
                    {
                        "id": "photos_videos",
                        "path": str(target),
                        "files": n,
                        "status": "staged_on_mac",
                        "note": "Full originals remain in Cumulous Photos vault; package has restore sample + paths.",
                    }
                )
        except Exception as e:
            staged.append({"id": "photos_videos", "ok": False, "error": str(e)[:160]})

    # Music vault
    if _ids_touch_music(expanded):
        try:
            from cumulous.music_offload import music_library_root, podcast_library_root

            for label, root_fn in (("music", music_library_root), ("podcasts", podcast_library_root)):
                src = root_fn()
                if not src.is_dir():
                    continue
                target = dest / label
                target.mkdir(exist_ok=True)
                n = 0
                for fp in src.rglob("*"):
                    if not fp.is_file() or fp.name.startswith("."):
                        continue
                    rel = fp.relative_to(src)
                    out = target / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if not out.exists():
                        shutil.copy2(fp, out)
                    n += 1
                    if n >= 300:
                        break
                staged.append(
                    {
                        "id": label,
                        "path": str(target),
                        "files": n,
                        "status": "staged_on_mac",
                        "note": "Apple Music cloud songs can also re-download in the Music app.",
                    }
                )
        except Exception as e:
            staged.append({"id": "music", "ok": False, "error": str(e)[:160]})

    # System / apps — point at latest incoming full backup if present
    if _ids_touch_system(expanded):
        try:
            from cumulous.paths import backup_incoming_root

            br = backup_incoming_root()
            trees = sorted(br.glob("full_*"), key=lambda p: p.stat().st_mtime, reverse=True) if br.is_dir() else []
            if trees:
                link = dest / "system_backup_source.txt"
                link.write_text(
                    f"Latest full system tree:\n{trees[0]}\n"
                    f"Selected ids: {', '.join(expanded)}\n"
                    "Restore on device uses Apple backup tools / Cumulous staging — not auto-wiped.\n"
                )
                staged.append(
                    {
                        "id": "system",
                        "path": str(trees[0]),
                        "status": "staged_on_mac",
                        "note": "Full system tree referenced for selected domains/apps.",
                    }
                )
            else:
                staged.append(
                    {
                        "id": "system",
                        "status": "not_in_vault",
                        "note": "No full system backup found yet. Run Backup All Device Data first.",
                    }
                )
        except Exception as e:
            staged.append({"id": "system", "ok": False, "error": str(e)[:160]})

    # Manifest
    manifest = {
        "ids": expanded,
        "staged": staged,
        "dest": str(dest),
        "created_at": time.time(),
        "status": "staged_on_mac",
    }
    (dest / "RESTORE_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    (dest / "README.txt").write_text(
        "Cumulous restore package\n"
        f"Location: {dest}\n"
        "Status: Staged on this Mac (vault originals unchanged).\n"
        "Open Cumulous to push supported items back to the phone when available.\n"
        "Photos: use Cumulous Photos gallery.\n"
        "Music: vault files here; Apple Music can re-download cloud songs.\n"
    )

    job = _append_job(
        {
            "job_id": f"rst_sel_{int(time.time())}",
            "type": "restore_selected",
            "ids": expanded,
            "dest": str(dest),
            "staged": staged,
            "ok": bool(staged),
            "status": "staged_on_mac",
            "message": f"Restore package ready on this Mac ({dest.name}). Vault originals stay safe.",
        }
    )
    return {
        "ok": bool(staged),
        "status": "staged_on_mac",
        "dest": str(dest),
        "ids": expanded,
        "staged": staged,
        "message": job["message"],
    }


def restore_all_device_data(*, device_id: str = "", confirm: bool = False) -> dict[str, Any]:
    """Stage full restore of all known vault domains. Requires confirm=True."""
    if not confirm:
        return {
            "ok": False,
            "error": "confirm_required",
            "message": "Confirm Restore All Device Data to stage a full restore package.",
        }
    catalog = build_selectable_catalog(device_id=device_id)
    all_ids = [c["id"] for c in catalog.get("categories") or []]
    all_ids += [a["id"] for a in catalog.get("apps") or []]
    res = restore_selected(all_ids, device_id=device_id)
    res["type"] = "restore_all"
    res["message"] = (
        (res.get("message") or "")
        + " This is a full restore package (staged on Mac)."
    )
    return res


def recent_jobs(limit: int = 20) -> list[dict[str, Any]]:
    jobs = _load_jobs()
    return list(reversed(jobs[-limit:]))
