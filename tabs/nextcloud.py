import shutil
from pathlib import Path

import streamlit as st

NC_LOCAL = "http://localhost:8080"
STORAGE_CANDIDATES = [
    Path("/Volumes/ExternalSSD"),
    Path.home() / "NextcloudAIO",
]


def render(profile: dict | None) -> None:
    st.header("Nextcloud")
    st.caption("DelphiBEAR cloud — photos, files, backups on Seagate HDD.")

    st.link_button("Open Nextcloud", NC_LOCAL)

    c1, c2, c3 = st.columns(3)
    mount = next((p for p in STORAGE_CANDIDATES if p.exists()), None)
    if mount:
        usage = shutil.disk_usage(mount)
        c1.metric("Storage mount", mount.name)
        c2.metric("Total", f"{usage.total // (1024**3)} GB")
        c3.metric("Free", f"{usage.free // (1024**3)} GB")
    else:
        c1.warning("ExternalSSD not mounted")

    st.subheader("Sync status")
    st.info("Connect Nextcloud AIO Docker (see PLAN PR-07). Auto-upload from iPhone via official app.")