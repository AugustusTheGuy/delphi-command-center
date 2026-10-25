"""Ingest large on-disk system backups efficiently.

Full idevicebackup2 trees are kept on ExternalSSD (CumulousIncoming) and catalogued
into the progressive vault with a sealed manifest + sparse sealed samples.
Per-file PBKDF2 sealing of multi‑GB trees is intentionally avoided.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from cumulous.crypto_vault import write_sealed_file
from cumulous.paths import device_dir
from cumulous.progressive_backup import generation_path, head_path, journal_path


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


def catalog_tree(source: Path, *, max_files: int = 200_000) -> list[dict]:
    source = source.expanduser().resolve()
    entries: list[dict] = []
    for root, _dirs, names in os.walk(source):
        for name in names:
            if name.startswith("."):
                continue
            p = Path(root) / name
            try:
                digest, size = _sha256_file(p)
                rel = str(p.relative_to(source))
            except OSError:
                continue
            entries.append({"path": rel, "digest": digest, "size": size, "abs": str(p)})
            if len(entries) >= max_files:
                return entries
    return entries


def ingest_tree(
    device_id: str,
    source: Path,
    password: str,
    *,
    mode: str = "persistent",
    max_files: int = 200_000,
    sample_seal_limit: int = 40,
) -> dict[str, Any]:
    """Catalog full tree on HDD; seal manifest + small sample into vault."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        return {"ok": False, "error": "source_not_dir"}

    entries = catalog_tree(source, max_files=max_files)
    if not entries:
        return {"ok": False, "error": "no_files"}

    total_bytes = sum(e["size"] for e in entries)
    # Seal a small sample of smaller files so vault has real encrypted content
    samples: list[dict] = []
    sealed = 0
    for e in sorted(entries, key=lambda x: x["size"])[:sample_seal_limit]:
        if e["size"] > 2 * 1024 * 1024:
            continue
        try:
            data = Path(e["abs"]).read_bytes()
            bp = device_dir(device_id) / "blobs" / e["digest"]
            if not bp.exists():
                write_sealed_file(bp, data, password, device_id=device_id)
                sealed += 1
            samples.append({"path": e["path"], "digest": e["digest"], "size": e["size"]})
        except OSError:
            continue

    catalog_body = {
        "kind": "idevicebackup2_external",
        "source": str(source),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "files": [{"path": e["path"], "digest": e["digest"], "size": e["size"]} for e in entries],
        "storage": "externalssd_or_incoming_raw",
        "note": (
            "Full system files live on the path in source=; "
            "vault stores catalog + sample sealed blobs."
        ),
    }
    catalog_bytes = json.dumps(catalog_body, separators=(",", ":"), sort_keys=True).encode()
    cat_digest = hashlib.sha256(catalog_bytes).hexdigest()
    write_sealed_file(
        device_dir(device_id) / "blobs" / cat_digest,
        catalog_bytes,
        password,
        device_id=device_id,
    )

    gen_id = f"gen_{int(time.time())}_{cat_digest[:10]}"
    prev = None
    hp = head_path(device_id)
    if hp.exists():
        prev = hp.read_text().strip() or None

    manifest = {
        "gen_id": gen_id,
        "parent": prev,
        "created_at": time.time(),
        "strategy": "full_system_catalog",
        "mode": mode,
        "categories": ["system_backup", "idevicebackup2", "photos", "files", "sms", "notes"],
        "files": [
            {"path": "cumulous/system_catalog.json", "digest": cat_digest, "size": len(catalog_bytes)},
            *samples,
        ],
        "file_count": 1 + len(samples),
        "total_bytes": len(catalog_bytes) + sum(s["size"] for s in samples),
        "external_system_backup": {
            "path": str(source),
            "file_count": len(entries),
            "total_bytes": total_bytes,
            "complete": False,  # may be partial if transfer aborted
        },
        "blobs_newly_sealed": sealed + 1,
    }
    generation_path(device_id, gen_id).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    head_path(device_id).write_text(gen_id)
    with journal_path(device_id).open("a") as j:
        j.write(json.dumps({"ts": time.time(), "gen_id": gen_id, "strategy": "full_system_catalog", "external_files": len(entries)}) + "\n")

    return {
        "ok": True,
        "status": "ok",
        "head": gen_id,
        "external_files": len(entries),
        "external_bytes": total_bytes,
        "external_path": str(source),
        "vault_samples": len(samples),
        "blobs_newly_sealed": sealed + 1,
    }
