import streamlit as st

from core.profiles import ALL_TABS, create_profile, list_profiles, load_profile, save_profile
from core.theme import PRIMARY, SECONDARY, TERTIARY_LIGHT, palette_for, sanitize_color, save_appearance


def _color_row(prefix: str, current: dict) -> tuple[str, str, str]:
    c1, c2, c3 = st.columns(3)
    primary = c1.color_picker("Metal", sanitize_color(current.get("primary") or "", PRIMARY), key=f"{prefix}_primary")
    secondary = c2.color_picker("Highlight", sanitize_color(current.get("secondary") or "", SECONDARY), key=f"{prefix}_secondary")
    tertiary = c3.color_picker("Background", sanitize_color(current.get("tertiary") or "", TERTIARY_LIGHT), key=f"{prefix}_tertiary")
    return primary, secondary, tertiary


def render(profile: dict | None) -> None:
    st.header("Profile")
    st.caption("Pick the metal color, the green highlight, and the background. Choose which pages this profile opens.")

    active_id = st.session_state.get("active_profile_id")
    active = load_profile(active_id) if active_id else None
    if active:
        st.subheader(f"Current profile colors · {active.get('name', 'Profile')}")
        look = palette_for(active)
        primary, secondary, tertiary = _color_row("current", look)
        if st.button("Save colors", key="save_current_colors"):
            active["primary_color"] = primary
            active["secondary_color"] = secondary
            active["tertiary_color"] = tertiary
            save_profile(active)
            st.success("Colors saved for this profile.")
            st.rerun()
    else:
        st.subheader("Command Center colors")
        look = palette_for(None)
        primary, secondary, tertiary = _color_row("appearance", look)
        if st.button("Save colors", key="save_appearance_colors"):
            save_appearance(primary, secondary, tertiary)
            st.success("Colors saved for this Mac.")
            st.rerun()

    col_create, col_list = st.columns([1, 1])

    with col_create:
        st.subheader("Create Profile")
        if st.button("Create profile", key="show_create_profile_btn"):
            st.session_state["show_create_profile"] = True
            st.session_state["show_create_profile"] = True

        if st.session_state.get("show_create_profile"):
            name = st.text_input("Profile name")
            primary, secondary, tertiary = _color_row("new", {})
            st.markdown("**Enabled tabs**")
            enabled = {}
            for tab in ALL_TABS:
                if tab == "user_profile":
                    continue
                enabled[tab] = st.checkbox(tab.replace("_", " ").title(), value=True, key=f"new_{tab}")
            if st.button("Save Profile"):
                if name.strip():
                    pid = create_profile(name.strip(), primary, secondary, tertiary, enabled)
                    st.session_state["active_profile_id"] = pid
                    st.session_state["show_create_profile"] = False
                    st.success(f"Profile '{name}' created.")
                    st.rerun()

    with col_list:
        st.subheader("Profiles")
        for p in list_profiles():
            prof = load_profile(p["id"])
            color = p.get("primary_color", PRIMARY)
            cols = st.columns([0.15, 0.85])
            with cols[0]:
                st.markdown(f"<span style='font-size:1.5rem;color:{color}'>●</span>", unsafe_allow_html=True)
            with cols[1]:
                label = f"**{p['name']}**"
                if st.button(label, key=f"sel_{p['id']}"):
                    st.session_state["active_profile_id"] = p["id"]
                    st.rerun()
            if prof and prof.get("avatar"):
                st.caption("Avatar set")