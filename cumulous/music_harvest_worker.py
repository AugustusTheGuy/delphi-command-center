"""Detached music + podcast harvest worker (nohup-friendly).

Env:
  CUMULOUS_MUSIC_HARVEST_DEVICE_ID
  CUMULOUS_MUSIC_HARVEST_UDID
  CUMULOUS_MUSIC_HARVEST_APPLE_ID
  CUMULOUS_MUSIC_HARVEST_LIMIT (optional)
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    device_id = os.environ.get("CUMULOUS_MUSIC_HARVEST_DEVICE_ID") or ""
    udid = os.environ.get("CUMULOUS_MUSIC_HARVEST_UDID") or ""
    apple_id = os.environ.get("CUMULOUS_MUSIC_HARVEST_APPLE_ID") or ""
    limit_s = os.environ.get("CUMULOUS_MUSIC_HARVEST_LIMIT") or ""
    limit = int(limit_s) if limit_s.isdigit() else None

    from cumulous.device_power import begin_backup_wake_policy, end_backup_wake_policy
    from cumulous.music_offload import harvest_music_afc

    begin_backup_wake_policy(
        session_id=f"music_harvest_worker_{device_id or udid}",
        device_name="ROB IPHONE (2)",
    )
    try:
        res = harvest_music_afc(
            device_id=device_id,
            udid=udid,
            apple_account_id=apple_id,
            limit=limit,
        )
        print(
            "music_harvest_done",
            res.get("status"),
            "mirrored",
            res.get("mirrored"),
            "dual_ok",
            res.get("dual_ok"),
            "playlists_untouched",
            True,
            flush=True,
        )
        return 0 if res.get("ok") else 1
    finally:
        end_backup_wake_policy(reason="music_harvest_worker_exit")


if __name__ == "__main__":
    sys.exit(main())
