"""Detached photo harvest worker (nohup-friendly).

Env:
  CUMULOUS_HARVEST_DEVICE_ID
  CUMULOUS_HARVEST_UDID
  CUMULOUS_HARVEST_APPLE_ID
  CUMULOUS_HARVEST_LIMIT (optional)
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    device_id = os.environ.get("CUMULOUS_HARVEST_DEVICE_ID") or ""
    udid = os.environ.get("CUMULOUS_HARVEST_UDID") or ""
    apple_id = os.environ.get("CUMULOUS_HARVEST_APPLE_ID") or ""
    limit_s = os.environ.get("CUMULOUS_HARVEST_LIMIT") or ""
    limit = int(limit_s) if limit_s.isdigit() else None

    from cumulous.device_power import begin_backup_wake_policy, end_backup_wake_policy
    from cumulous.photo_offload import harvest_device_media_afc

    begin_backup_wake_policy(
        session_id=f"harvest_worker_{device_id or udid}",
        device_name="ROB IPHONE (2)",
    )
    try:
        res = harvest_device_media_afc(
            device_id=device_id,
            udid=udid,
            apple_account_id=apple_id,
            limit=limit,
        )
        print("harvest_done", res.get("status"), "mirrored", res.get("mirrored"), flush=True)
        return 0 if res.get("ok") else 1
    finally:
        end_backup_wake_policy(reason="harvest_worker_exit")


if __name__ == "__main__":
    sys.exit(main())
