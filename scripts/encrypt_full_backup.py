#!/usr/bin/env python3
"""After idevicebackup2 finishes, seal the tree into Cumulous progressive vault."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cumulous.backup_ops import load_vault_password, secure_backup_device  # noqa: E402
from cumulous.companion import collect_files  # noqa: E402
from cumulous.device_bridge import fingerprint_files, verify_against_generation  # noqa: E402
from cumulous.progressive_backup import create_generation  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "")
    if not path.is_dir():
        marker = Path("/tmp/cumulous_full_backup_path.txt")
        if marker.exists():
            path = Path(marker.read_text().strip())
    if not path.is_dir():
        print({"ok": False, "error": "no_incoming_dir"})
        return 1

    device_id = sys.argv[2] if len(sys.argv) > 2 else "354345290021725"
    password = load_vault_password()
    if not password:
        print({"ok": False, "error": "no_vault_password"})
        return 1

    print({"phase": "collect", "path": str(path)})
    files = collect_files(path, limit=50_000)
    # also include identity snapshot keys
    from cumulous.backup_ops import device_identity_snapshot

    for k, v in device_identity_snapshot().items():
        files[k] = v
    print({"phase": "encrypt", "file_count": len(files)})
    t0 = fingerprint_files(files)
    result = create_generation(
        device_id,
        files,
        password,
        mode="persistent",
        categories=["system_backup", "photos", "sms", "notes", "files", "identity"],
    )
    if result.get("status") == "ok":
        result["verification"] = verify_against_generation(device_id, result["head"], t0)
    result["ok"] = result.get("status") in ("ok", "up_to_date")
    result["source"] = str(path)
    result["file_count"] = len(files)
    print({k: result.get(k) for k in ("ok", "status", "head", "file_count", "verification", "strategy")})
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
