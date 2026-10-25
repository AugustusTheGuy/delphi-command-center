"""PhantomCloak tab — DSI/VPN integration (formerly VPN/DSI)."""

from __future__ import annotations

import streamlit as st

from core.phantomcloak_bridge import launch, status, verify_up_to_date


def render(profile: dict | None) -> None:
    st.header("PhantomCloak")
    st.caption("DSI/VPN Command Center — persistent version verify on DHC open")

    if "phantom_status" not in st.session_state:
        st.session_state.phantom_status = verify_up_to_date()

    if st.button("Refresh status"):
        st.session_state.phantom_status = verify_up_to_date()
        st.rerun()

    stt = st.session_state.phantom_status
    c1, c2, c3 = st.columns(3)
    c1.metric("Installed", "Yes" if stt.get("installed") else "No")
    c2.metric("Version", stt.get("version", "?"))
    c3.metric("Up to date", "Yes" if stt.get("up_to_date") else "Check")

    if not stt.get("up_to_date") and stt.get("installed"):
        st.warning("PhantomCloak may have local changes or updates available. Run install script to sync.")

    st.code(stt.get("path", ""))

    if st.button("Launch PhantomCloak", type="primary"):
        ok, msg = launch()
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    if stt.get("last_session"):
        with st.expander("Last session"):
            st.json(stt["last_session"])

    st.markdown(
        """
        **Capabilities (via PhantomCloak app)**
        - Residential VPN pools · purpose-based profiles
        - Tracker vault · anti-detection browser profiles
        - Health harness · security audit
        - Translation engine · content catalog
        """
    )