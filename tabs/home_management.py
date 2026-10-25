import streamlit as st

from core.homeassistant_client import call_service, list_states, ping

HA_URL = "http://localhost:8123"


def render(profile: dict | None) -> None:
    st.header("Home Management")
    st.caption("PR-04 — HomeKit + Home Assistant API")

    ha_ok = ping()
    st.metric("Home Assistant", "Reachable" if ha_ok else "Offline (start Docker HA)")

    st.link_button("Open Home Assistant", HA_URL)

    if ha_ok:
        states = list_states()[:12]
        if states:
            st.subheader("Entity snapshot")
            for s in states:
                st.caption(f"{s.get('entity_id')} → {s.get('state')}")

    st.markdown(
        """
        **Planned automations**
        - Movie mode: dim lights, cast to Samsung TV
        - Voice via iPhone Shortcuts → Tailscale → HA
        - SpaceX/WiFi status in scenes
        """
    )
    devices = st.multiselect(
        "Rooms",
        ["Living Room TV", "Bedroom TV", "Office lights", "Thermostat"],
        default=["Living Room TV"],
    )
    if st.button("Run Movie Mode"):
        if ha_ok:
            call_service("scene", "turn_on", data={"entity_id": "scene.movie_mode"})
        st.success(f"Scene queued for: {', '.join(devices)}")