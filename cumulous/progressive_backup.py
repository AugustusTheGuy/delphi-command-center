"""Single progressive backup chain: content-addressed blobs + HEAD + generations."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cumulous.crypto_vault import read_sealed_file, write_sealed_file
from cumulous.paths import device_dir


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def head_path(device_id: str) -> Path:
    return device_dir(device_id) / "HEAD"


def journal_path(device_id: str) -> Path:
    return device_dir(device_id) / "journal.jsonl"


def blob_path(device_id: str, digest: str) -> Path:
    return device_dir(device_id) / "blobs" / digest


def generation_path(device_id: str, gen_id: str) -> Path:
    return device_dir(device_id) / "generations" / f"{gen_id}.manifest.json"


def current_head(device_id: str) -> str | None:
    p = head_path(device_id)
    if not p.exists():
        return None
    return p.read_text().strip() or None


def put_blob(device_id: str, data: bytes, password: str) -> str:
    digest = _sha256(data)
    bp = blob_path(device_id, digest)
    if not bp.exists():
        write_sealed_file(bp, data, password, device_id=device_id)
    return digest


def get_blob(device_id: str, digest: str, password: str) -> bytes:
    return read_sealed_file(blob_path(device_id, digest), password, device_id=device_id)


@dataclass
class FileEntry:
    path: str
    digest: str
    size: int


def inventory_from_files(files: dict[str, bytes]) -> dict[str, FileEntry]:
    return {
        path: FileEntry(path=path, digest=_sha256(data), size=len(data))
        for path, data in files.items()
    }


def decide_strategy(prev: dict[str, str] | None, new_map: dict[str, str]) -> str:
    """Return 'baseline' | 'incremental' | 'full_manifest' | 'noop'."""
    if not prev:
        return "baseline"
    prev_paths, new_paths = set(prev), set(new_map)
    deleted = prev_paths - new_paths
    added = new_paths - prev_paths
    changed = {p for p in prev_paths & new_paths if prev[p] != new_map[p]}
    if not deleted and not added and not changed:
        return "noop"
    if deleted:
        return "full_manifest"
    return "incremental"


def create_generation(
    device_id: str,
    files: dict[str, bytes],
    password: str,
    *,
    categories: Iterable[str] | None = None,
    mode: str = "standard",
) -> dict:
    """Store blobs, write generation manifest, advance HEAD, append journal."""
    ddir = device_dir(device_id)
    new_map = {p: _sha256(b) for p, b in files.items()}
    prev_id = current_head(device_id)
    prev_map: dict[str, str] | None = None
    if prev_id:
        prev_man = _read_json(generation_path(device_id, prev_id))
        prev_map = {e["path"]: e["digest"] for e in prev_man.get("files", [])}

    strategy = decide_strategy(prev_map, new_map)
    if strategy == "noop":
        return {"status": "up_to_date", "head": prev_id, "strategy": strategy}

    # store new blobs only
    for path, data in files.items():
        put_blob(device_id, data, password)

    gen_id = f"gen_{int(time.time())}_{_sha256(json.dumps(new_map, sort_keys=True).encode())[:10]}"
    manifest = {
        "gen_id": gen_id,
        "parent": prev_id,
        "created_at": time.time(),
        "strategy": strategy,
        "mode": mode,
        "categories": list(categories or []),
        "files": [{"path": p, "digest": d, "size": len(files[p])} for p, d in sorted(new_map.items())],
        "file_count": len(new_map),
        "total_bytes": sum(len(b) for b in files.values()),
    }
    _write_json(generation_path(device_id, gen_id), manifest)
    head_path(device_id).write_text(gen_id)
    with journal_path(device_id).open("a") as j:
        j.write(
            json.dumps(
                {
                    "ts": time.time(),
                    "gen_id": gen_id,
                    "strategy": strategy,
                    "file_count": len(new_map),
                }
            )
            + "\n"
        )
    return {"status": "ok", "head": gen_id, "strategy": strategy, "manifest": manifest}


def restore_generation(device_id: str, gen_id: str, password: str) -> dict[str, bytes]:
    man = _read_json(generation_path(device_id, gen_id))
    out: dict[str, bytes] = {}
    for e in man.get("files", []):
        out[e["path"]] = get_blob(device_id, e["digest"], password)
    return out


def content_diff_ratio(a: dict[str, str], b: dict[str, str]) -> float:
    """Fraction of paths that differ (0..1). Used for 30% retention rule."""
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    diff = sum(1 for k in keys if a.get(k) != b.get(k))
    return diff / len(keys)


def apply_retention(device_id: str, *, months: float = 3.0, min_diff: float = 0.30) -> dict:
    """Keep gen0 + HEAD; after 3 months drop gens with <30% difference from nearest kept."""
    gens_dir = device_dir(device_id) / "generations"
    manifests = sorted(gens_dir.glob("*.manifest.json"))
    if not manifests:
        return {"kept": [], "removed": []}

    loaded = []
    for p in manifests:
        m = _read_json(p)
        m["_path"] = str(p)
        loaded.append(m)
    loaded.sort(key=lambda m: m.get("created_at", 0))

    now = time.time()
    cutoff = now - months * 30 * 24 * 3600
    head = current_head(device_id)
    kept: list[dict] = []
    removed: list[str] = []

    # always keep first and head
    for i, m in enumerate(loaded):
        is_first = i == 0
        is_head = m.get("gen_id") == head
        if is_first or is_head:
            kept.append(m)
            continue
        if m.get("created_at", 0) >= cutoff:
            kept.append(m)
            continue
        # older than 3 months: keep only if >= min_diff from last kept
        last_map = {e["path"]: e["digest"] for e in kept[-1].get("files", [])}
        this_map = {e["path"]: e["digest"] for e in m.get("files", [])}
        if content_diff_ratio(last_map, this_map) >= min_diff:
            kept.append(m)
        else:
            removed.append(m["gen_id"])
            Path(m["_path"]).unlink(missing_ok=True)

    # GC unreferenced blobs
    referenced: set[str] = set()
    for m in kept:
        for e in m.get("files", []):
            referenced.add(e["digest"])
    blobs_dir = device_dir(device_id) / "blobs"
    gc = 0
    if blobs_dir.is_dir():
        for bp in blobs_dir.iterdir():
            if bp.name not in referenced:
                bp.unlink(missing_ok=True)
                gc += 1
    return {"kept": [m["gen_id"] for m in kept], "removed": removed, "blobs_gc": gc}
