"""Intelligent iPhone storage optimization for Cumulous.

Principle (never violate):
  1. Vault copies on Mac HDD + Nextcloud are never deleted by this pass.
  2. Only dual-verified (or hdd-only if policy allows) media is eligible.
  3. Hard protects (Snapchat / Favorites / album names) always win.
  4. Soft protects (recent N days) use a client-must / age signal when known.
  5. Optimization is an optional pre-backup phase the user must confirm.

Math model (maximize expected freeable bytes under safety constraints):

  For each candidate i with size s_i, age_days a_i, restore confidence c_i ∈ (0,1]:
      score_i = s_i * c_i * age_weight(a_i) * type_weight(kind_i)

  age_weight(a) = 1 / (1 + exp(-(a - keep_days) / 14))
      → logistic ramp: near 0 for recent media, ~1 for older than keep window

  type_weight: video > photo (videos free more bytes per delete)

  Select set S maximizing Σ score_i  subject to:
      - all i dual-verified & not protected
      - optional min_bytes / max_items
      - greedy by score_i descending is optimal for this linear score with
        independent items (0-1 knapsack with infinite capacity = sort by score)

Execution: plan (dry-run) → optional re-verify sample → AFC/iOS queue deletes.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal

from cumulous.paths import ensure_internal
from cumulous.photo_offload import (
    freeable_on_device,
    load_mirror_index,
    load_prefs,
    mark_deleted_on_device,
    request_device_delete,
    save_prefs,
    usb_device_present,
    _should_keep_on_device,
)

Mode = Literal["conservative", "balanced", "aggressive"]

STATE_FILE = "storage_optimize_state.json"
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".3gp", ".avi"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp"}


def _state_path() -> Path:
    return ensure_internal() / STATE_FILE


def load_opt_state() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_opt_state(data: dict[str, Any]) -> None:
    ensure_internal()
    data["updated_at"] = time.time()
    p = _state_path()
    p.write_text(json.dumps(data, indent=2))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def _ext(name: str) -> str:
    return Path(name or "").suffix.lower()


def _kind(name: str) -> str:
    e = _ext(name)
    if e in VIDEO_EXT:
        return "video"
    if e in PHOTO_EXT:
        return "photo"
    return "other"


def _age_days(item: dict[str, Any]) -> float | None:
    """Best-effort age in days from tags or mtime."""
    dig = item.get("digest") or ""
    try:
        from cumulous.photo_tagging import get_tags

        tags = get_tags(dig) or {}
        ts = tags.get("captured_at")
        if ts:
            return max(0.0, (time.time() - float(ts)) / 86400.0)
    except Exception:
        pass
    # mtime on HDD path
    path = item.get("hdd_path") or ""
    if path:
        try:
            m = Path(path).stat().st_mtime
            return max(0.0, (time.time() - m) / 86400.0)
        except Exception:
            pass
    ua = item.get("updated_at")
    if ua:
        try:
            return max(0.0, (time.time() - float(ua)) / 86400.0)
        except Exception:
            pass
    return None


def _restore_confidence(item: dict[str, Any]) -> float:
    """c ∈ (0,1]: how sure we can restore from vault alone."""
    hdd = bool(item.get("hdd_ok"))
    nc = bool(item.get("nextcloud_ok"))
    path = item.get("hdd_path") or ""
    size = int(item.get("size") or 0)
    c = 0.35
    if hdd:
        c += 0.35
    if nc:
        c += 0.25
    if path and Path(str(path)).is_file():
        try:
            on_disk = Path(str(path)).stat().st_size
            if size > 0 and on_disk == size:
                c += 0.05
            elif on_disk > 0:
                c += 0.02
        except Exception:
            pass
    return min(1.0, max(0.05, c))


def _age_weight(age_days: float | None, keep_days: int) -> float:
    """Logistic: soft zero for recent, approaches 1 after keep window."""
    if age_days is None:
        # Unknown age: conservative mid weight (don't treat as ancient)
        return 0.45
    # center at keep_days, scale 14 days
    x = (float(age_days) - float(keep_days)) / 14.0
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _type_weight(kind: str, mode: Mode) -> float:
    if kind == "video":
        return 1.25 if mode != "conservative" else 1.1
    if kind == "photo":
        return 1.0
    return 0.7


def _mode_params(mode: Mode) -> dict[str, Any]:
    if mode == "conservative":
        return {
            "min_confidence": 0.85,
            "min_age_days": 180,
            "min_size_bytes": 2 * 1024 * 1024,  # 2 MB
            "prefer_videos": True,
        }
    if mode == "aggressive":
        return {
            "min_confidence": 0.70,
            "min_age_days": 30,
            "min_size_bytes": 0,
            "prefer_videos": True,
        }
    # balanced
    return {
        "min_confidence": 0.80,
        "min_age_days": 90,
        "min_size_bytes": 256 * 1024,
        "prefer_videos": True,
    }


@dataclass
class Candidate:
    digest: str
    name: str
    size: int
    kind: str
    age_days: float | None
    confidence: float
    score: float
    hdd_ok: bool
    nextcloud_ok: bool
    local_asset_id: str = ""
    device_id: str = ""
    reasons: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["size_mb"] = round(self.size / (1024 * 1024), 2)
        return d


def build_candidates(
    *,
    device_id: str = "",
    mode: Mode = "balanced",
) -> list[Candidate]:
    prefs = load_prefs()
    keep_days = int(prefs.get("keep_on_device_days") or 180)
    params = _mode_params(mode)
    raw = freeable_on_device(device_id=device_id, dual_only=True, respect_protect=True)
    # Also include dual-ok not yet flagged freeable if confidence high
    idx = load_mirror_index().get("items") or {}
    seen = {r.get("digest") for r in raw}
    for dig, it in idx.items():
        if dig in seen:
            continue
        if it.get("deleted_on_device"):
            continue
        if not (it.get("hdd_ok") and it.get("nextcloud_ok")):
            continue
        if device_id and str(it.get("device_id") or "") not in ("", str(device_id)):
            continue
        prot = _should_keep_on_device(
            prefs,
            name=str(it.get("name") or ""),
            local_asset_id=str(it.get("local_asset_id") or ""),
        )
        hard = [r for r in (prot.get("reasons") or []) if not str(r).startswith("client_must")]
        if hard:
            continue
        raw.append({**it, "digest": dig})

    cands: list[Candidate] = []
    for it in raw:
        dig = str(it.get("digest") or "")
        if not dig:
            continue
        name = str(it.get("name") or "")
        size = int(it.get("size") or 0)
        if size < int(params["min_size_bytes"]):
            continue
        kind = _kind(name)
        age = _age_days(it)
        # Enforce min age when known
        if age is not None and age < float(params["min_age_days"]):
            # aggressive allows younger; still skip very new (<7d) always
            if mode != "aggressive" or age < 7:
                continue
        conf = _restore_confidence(it)
        if conf < float(params["min_confidence"]):
            continue
        aw = _age_weight(age, keep_days)
        tw = _type_weight(kind, mode)
        score = float(size) * conf * aw * tw
        reasons = [
            f"dual={'yes' if it.get('hdd_ok') and it.get('nextcloud_ok') else 'no'}",
            f"conf={conf:.2f}",
            f"age_d={age:.0f}" if age is not None else "age=unknown",
            f"kind={kind}",
        ]
        cands.append(
            Candidate(
                digest=dig,
                name=name,
                size=size,
                kind=kind,
                age_days=age,
                confidence=conf,
                score=score,
                hdd_ok=bool(it.get("hdd_ok")),
                nextcloud_ok=bool(it.get("nextcloud_ok")),
                local_asset_id=str(it.get("local_asset_id") or ""),
                device_id=str(it.get("device_id") or device_id or ""),
                reasons=reasons,
            )
        )
    # Greedy optimal for independent linear scores: sort by score desc
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands


def plan_optimization(
    *,
    device_id: str = "",
    mode: Mode = "balanced",
    max_items: int | None = None,
    target_bytes: int | None = None,
) -> dict[str, Any]:
    """Dry-run: ranked freeable set + projected savings (vault untouched)."""
    cands = build_candidates(device_id=device_id, mode=mode)
    selected: list[Candidate] = []
    bytes_sum = 0
    for c in cands:
        if max_items is not None and len(selected) >= max_items:
            break
        if target_bytes is not None and bytes_sum >= target_bytes:
            break
        selected.append(c)
        bytes_sum += c.size

    by_kind: dict[str, dict[str, int]] = {}
    for c in selected:
        b = by_kind.setdefault(c.kind, {"count": 0, "bytes": 0})
        b["count"] += 1
        b["bytes"] += c.size

    usb = usb_device_present()
    plan = {
        "ok": True,
        "dry_run": True,
        "mode": mode,
        "device_id": device_id or usb.get("device_id") or "",
        "device_name": usb.get("display_name") or "",
        "usb": bool(usb.get("usb")),
        "candidates_total": len(cands),
        "selected_count": len(selected),
        "projected_bytes": bytes_sum,
        "projected_mb": round(bytes_sum / (1024 * 1024), 1),
        "projected_gb": round(bytes_sum / (1024 * 1024 * 1024), 3),
        "by_kind": by_kind,
        "min_confidence": min((c.confidence for c in selected), default=0),
        "avg_confidence": (
            round(sum(c.confidence for c in selected) / len(selected), 3) if selected else 0
        ),
        "items": [c.public() for c in selected[:200]],  # cap UI payload
        "policy": {
            "vault_never_deleted": True,
            "requires_dual_mirror": True,
            "protects": ["Snapchat", "Favorites", "keep albums", "recent window by mode"],
            "math": "maximize Σ size·confidence·age_weight·type_weight (greedy sort)",
        },
        "message": (
            f"Can free about {round(bytes_sum / (1024 * 1024), 1)} MB "
            f"({len(selected)} items) from the phone. Cumulous keeps every original."
            if selected
            else "Nothing safe to free yet — dual-mirror more photos first."
        ),
        "planned_at": time.time(),
    }
    st = load_opt_state()
    st["last_plan"] = {
        "mode": mode,
        "selected_count": len(selected),
        "projected_bytes": bytes_sum,
        "digests": [c.digest for c in selected],
        "planned_at": plan["planned_at"],
    }
    save_opt_state(st)
    return plan


def execute_optimization(
    *,
    device_id: str = "",
    mode: Mode = "balanced",
    source: str = "mac",
    max_items: int | None = None,
    target_bytes: int | None = None,
    digests: list[str] | None = None,
    execute_afc: bool = True,
) -> dict[str, Any]:
    """Execute planned free-space pass on the phone only."""
    src = (source or "mac").lower()
    if src not in ("mac", "ios"):
        src = "mac"

    if digests:
        # Re-score only requested digests that still qualify
        all_c = {c.digest: c for c in build_candidates(device_id=device_id, mode=mode)}
        selected = [all_c[d] for d in digests if d in all_c]
    else:
        plan = plan_optimization(
            device_id=device_id, mode=mode, max_items=max_items, target_bytes=target_bytes
        )
        digests = [i["digest"] for i in (plan.get("items") or [])]
        # full selection from plan state
        st = load_opt_state()
        digests = (st.get("last_plan") or {}).get("digests") or digests
        all_c = {c.digest: c for c in build_candidates(device_id=device_id, mode=mode)}
        selected = [all_c[d] for d in digests if d in all_c]

    if src == "mac" and execute_afc:
        usb = usb_device_present()
        if not usb.get("usb"):
            return {
                "ok": False,
                "error": "usb_required",
                "message": "Plug the iPhone into this Mac with USB to free storage from here.",
                "removed": 0,
                "queued": 0,
                "bytes_freed": 0,
            }

    removed = 0
    queued = 0
    errors = 0
    bytes_freed = 0
    details: list[dict[str, Any]] = []

    for c in selected:
        res = request_device_delete(
            c.digest,
            source=src,
            require_usb=(src == "mac"),
            execute_afc=execute_afc and src == "mac",
        )
        if res.get("ok") and not res.get("queued"):
            removed += 1
            bytes_freed += c.size
            details.append({"digest": c.digest, "status": "removed", "size": c.size})
        elif res.get("ok"):
            queued += 1
            bytes_freed += c.size  # will free when client/AFC completes
            details.append({"digest": c.digest, "status": "queued", "size": c.size})
        else:
            errors += 1
            details.append(
                {
                    "digest": c.digest,
                    "status": "error",
                    "error": res.get("error") or res.get("message"),
                }
            )

    result = {
        "ok": True,
        "dry_run": False,
        "mode": mode,
        "source": src,
        "selected": len(selected),
        "removed": removed,
        "queued": queued,
        "errors": errors,
        "bytes_freed": bytes_freed,
        "mb_freed": round(bytes_freed / (1024 * 1024), 1),
        "gb_freed": round(bytes_freed / (1024 * 1024 * 1024), 3),
        "vault_kept": True,
        "message": (
            f"Storage pass: {removed} removed, {queued} queued "
            f"(~{round(bytes_freed / (1024 * 1024), 1)} MB). All copies stay in Cumulous."
        ),
        "details_sample": details[:50],
        "finished_at": time.time(),
    }
    st = load_opt_state()
    st["last_run"] = result
    save_opt_state(st)
    return result


def prompt_pref_default() -> bool:
    """Whether UI should default the storage-optimize toggle to ON."""
    prefs = load_prefs()
    # Default ON if free_phone was desired, else OFF when ask_before_free
    if prefs.get("ask_before_free_phone"):
        return False
    return bool(prefs.get("free_phone_storage_after_backup", True))


def set_prompt_preference(*, offer_at_backup_start: bool, default_yes: bool | None = None) -> dict:
    prefs = load_prefs()
    prefs["storage_optimize_prompt_at_backup"] = bool(offer_at_backup_start)
    if default_yes is not None:
        prefs["storage_optimize_default_yes"] = bool(default_yes)
    save_prefs(prefs)
    return prefs


def should_prompt_at_backup() -> bool:
    prefs = load_prefs()
    # Always prompt by product requirement unless explicitly disabled
    return bool(prefs.get("storage_optimize_prompt_at_backup", True))


def backup_start_storage_gate(
    *,
    device_id: str = "",
    mode: Mode = "balanced",
    user_wants_optimize: bool | None = None,
    source: str = "mac",
    execute: bool = True,
) -> dict[str, Any]:
    """Called at the start of a backup flow.

    - Always returns a plan summary for the UI prompt.
    - If user_wants_optimize is True and execute, runs the pass first.
    - If None, only plans (UI must ask).
    """
    plan = plan_optimization(device_id=device_id, mode=mode)
    out: dict[str, Any] = {
        "ok": True,
        "prompt_required": should_prompt_at_backup(),
        "plan": plan,
        "optimized": False,
        "skipped": False,
        "message": plan.get("message") or "",
    }
    if user_wants_optimize is None:
        out["awaiting_user"] = True
        out["message"] = (
            "Free space on the iPhone before backup? "
            f"About {plan.get('projected_mb', 0)} MB safe to free "
            f"({plan.get('selected_count', 0)} items). Vault stays complete."
        )
        return out
    if not user_wants_optimize:
        out["skipped"] = True
        out["message"] = "Storage optimization skipped — starting backup."
        st = load_opt_state()
        st["last_skip_at"] = time.time()
        save_opt_state(st)
        return out
    if not execute:
        out["awaiting_execute"] = True
        return out
    run = execute_optimization(
        device_id=device_id,
        mode=mode,
        source=source,
        digests=(load_opt_state().get("last_plan") or {}).get("digests"),
    )
    out["optimized"] = bool(run.get("ok"))
    out["result"] = run
    out["message"] = run.get("message") or out["message"]
    return out
