"""Settings live on one page: video servers, the drive, and the log."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.media_index import clear_video_cache
from core.media_services import connection_summary, load_media_services, save_media_services
from tabs.front_page import render_trouble

ROOT = Path(__file__).resolve().parent.parent
NOX_REQUEST = ROOT / "data" / "nox_access.request"


def _keep(typed: str, saved: str) -> str:
    cleaned = typed.strip()
    return cleaned or saved


def render(profile: dict | None) -> None:
    del profile
    st.header("Settings")

    st.divider()
    st.markdown("**Video servers**")
    st.caption("Jellyfin searches that server. Sonarr only lists shows that already have files.")
    current = load_media_services()
    jellyfin_url = st.text_input("Jellyfin address", value=current["jellyfin_url"], key="jellyfin_url")
    jellyfin_key = st.text_input(
        "Jellyfin key",
        value="",
        type="password",
        key="jellyfin_key",
        placeholder="Already saved" if current["jellyfin_api_key"] else "",
    )
    sonarr_url = st.text_input("Sonarr address", value=current["sonarr_url"], key="sonarr_url")
    sonarr_key = st.text_input(
        "Sonarr key",
        value="",
        type="password",
        key="sonarr_key",
        placeholder="Already saved" if current["sonarr_api_key"] else "",
    )
    if st.button("Save video servers", key="save_media_services"):
        save_media_services(
            jellyfin_url.strip(),
            _keep(jellyfin_key, current["jellyfin_api_key"]),
            sonarr_url.strip(),
            _keep(sonarr_key, current["sonarr_api_key"]),
        )
        clear_video_cache()
        st.success("Video servers saved.")
    st.caption(connection_summary())

    st.divider()
    st.markdown("**ExternalSSD**")
    st.caption("Allow Command Center to save the library list on the drive. If the drive says no, the library stays open.")
    if st.button("Allow saving on ExternalSSD", key="nox_allow"):
        NOX_REQUEST.parent.mkdir(parents=True, exist_ok=True)
        NOX_REQUEST.write_text("1")
        st.success("Choose ExternalSSD in the window that opens.")

    st.divider()
    render_trouble()
