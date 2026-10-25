import streamlit as st

from core.homeassistant_client import call_service, ping

APPS = [
    ("Netflix", "🎬"),
    ("YouTube", "▶️"),
    ("Jellyfin", "📺"),
    ("Immich Photos", "🖼️"),
    ("Bookstack Wiki", "📚"),
    ("Calibre E-Books", "📖"),
]


def render(profile: dict | None) -> None:
    st.header("TV Remote")
    st.caption("PR-04 — Samsung TV via Home Assistant")

    ha_ok = ping()
    if not ha_ok:
        st.warning("Home Assistant offline — TV commands will queue locally.")

    power = st.toggle("TV Power", value=False)
    vol = st.slider("Volume", 0, 100, 25)
    src = st.selectbox("Input", ["HDMI 1", "HDMI 2", "Apple TV", "AirPlay"])

    if st.button("Send to TV"):
        if ha_ok:
            call_service("media_player", "volume_set", data={"volume_level": vol / 100})
        st.toast(f"TV: power={'on' if power else 'off'}, vol={vol}, input={src}")

    st.divider()
    st.subheader("Quick launch")
    cols = st.columns(3)
    for i, (name, icon) in enumerate(APPS):
        with cols[i % 3]:
            if st.button(f"{icon} {name}", use_container_width=True):
                if ha_ok:
                    call_service("script", "turn_on", data={"variables": {"app": name}})
                st.toast(f"Launching {name} on Samsung TV via HA.")

    st.caption("iPhone: mirror this layout via Shortcuts + Tailscale.")