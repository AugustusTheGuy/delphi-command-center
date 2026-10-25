"""Mac companion CLI — encrypt local tree into progressive vault."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from cumulous.device_bridge import fingerprint_files, verify_against_generation
from cumulous.progressive_backup import create_generation
from cumulous.paths import vault_root


def collect_files(source: Path, limit: int = 5000) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if source.is_file():
        files[source.name] = source.read_bytes()
        return files
    for root, _dirs, names in os.walk(source):
        for name in names:
            if name.startswith("."):
                continue
            p = Path(root) / name
            rel = str(p.relative_to(source))
            try:
                if p.stat().st_size > 50 * 1024 * 1024:
                    continue  # skip huge single files in basic mode
                files[rel] = p.read_bytes()
            except OSError:
                continue
            if len(files) >= limit:
                return files
    return files


def encrypt_ingest(
    source: Path,
    device_id: str,
    password: str,
    *,
    mode: str = "persistent",
) -> dict:
    files = collect_files(source)
    t0 = fingerprint_files(files)
    result = create_generation(device_id, files, password, mode=mode, categories=["files"])
    if result.get("status") == "ok":
        result["verification"] = verify_against_generation(device_id, result["head"], t0)
    result["vault"] = str(vault_root())
    result["file_count"] = len(files)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cumulous Mac companion")
    sub = p.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser("encrypt-ingest", help="Ingest folder into progressive vault")
    enc.add_argument("--source", required=True, type=Path)
    enc.add_argument("--device-id", required=True)
    enc.add_argument("--password", required=True)
    enc.add_argument("--mode", default="persistent")

    sub.add_parser("vault-path", help="Print vault root")

    args = p.parse_args(argv)
    if args.cmd == "vault-path":
        print(vault_root())
        return 0
    if args.cmd == "encrypt-ingest":
        out = encrypt_ingest(args.source, args.device_id, args.password, mode=args.mode)
        print(out)
        return 0 if out.get("status") in ("ok", "up_to_date") else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
