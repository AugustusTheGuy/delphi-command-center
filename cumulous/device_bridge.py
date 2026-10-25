"""Post-backup verification: compare generation inventory to t0 fingerprint."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from cumulous.paths import device_dir


def fingerprint_files(files: dict[str, bytes]) -> dict:
    """Capture device inventory fingerprint at backup start (t0)."""
    entries = []
    for path in sorted(files):
        data = files[path]
        entries.append(
            {
                "path": path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    return {
        "captured_at": time.time(),
        "file_count": len(entries),
        "total_bytes": sum(e["size"] for e in entries),
        "files": entries,
        "aggregate": hashlib.sha256(
            json.dumps([(e["path"], e["sha256"]) for e in entries]).encode()
        ).hexdigest(),
    }


def verify_against_generation(device_id: str, gen_id: str, t0: dict) -> dict:
    gen_path = device_dir(device_id) / "generations" / f"{gen_id}.manifest.json"
    man = json.loads(gen_path.read_text())
    gen_map = {e["path"]: e["digest"] for e in man.get("files", [])}
    t0_map = {e["path"]: e["sha256"] for e in t0.get("files", [])}

    missing = sorted(set(t0_map) - set(gen_map))
    extra = sorted(set(gen_map) - set(t0_map))
    mismatched = sorted(p for p in set(t0_map) & set(gen_map) if t0_map[p] != gen_map[p])
    total = max(len(t0_map), 1)
    match_count = total - len(missing) - len(mismatched)
    # don't count extra against match rate the same way
    rate = match_count / total

    if rate >= 0.999 and not missing and not mismatched:
        status = "verified"
    elif rate >= 0.95:
        status = "partial"
    else:
        status = "failed"

    report = {
        "gen_id": gen_id,
        "status": status,
        "match_rate": rate,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
        "verified_at": time.time(),
    }
    out = device_dir(device_id) / "verify" / f"{gen_id}.report.json"
    out.write_text(json.dumps(report, indent=2))
    return report
