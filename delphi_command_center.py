#!/usr/bin/env python3
"""
Delphi: Home Control — Command Center
Streamlit dashboard for M4 Mac Mini ecosystem.
"""

import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from components.splash import render_splash
from core.auth import ensure_default_user
from core.profiles import load_profile
from core.theme import get_theme_css, palette_for
from core.ui_state import load_page, save_page
from core.phantomcloak_bridge import verify_up_to_date
from hooks.persistent_hooks import run_startup_hooks
from tabs import agent_monitor, agents_dashboard, central_command, github_hf
from tabs import home_management, nextcloud, orchestrator, os_management, phantomcloak
from tabs import project_management, system_status, tv_remote, user_profile
from tabs import app_settings, front_page, video_library

TAB_MODULES = {
    "user_profile": ("User Profile", user_profile),
    "orchestrator": ("AI Orchestrator", orchestrator),
    "central_command": ("Central Command", central_command),
    "agent_monitor": ("Agent Monitor", agent_monitor),
    "agents_dashboard": ("Agents Dashboard", agents_dashboard),
    "system_status": ("System Status", system_status),
    "project_management": ("Projects", project_management),
    "home_management": ("Home", home_management),
    "nextcloud": ("Nextcloud", nextcloud),
    "video_library": ("Video Library", video_library),
    "tv_remote": ("TV Remote", tv_remote),
    "os_management": ("OS Management", os_management),
    "github_hf": ("GitHub / HF", github_hf),
    "phantomcloak": ("PhantomCloak", phantomcloak),
}


def _login_gate() -> bool:
    ensure_default_user()
    st.session_state["authenticated"] = True
    st.session_state["username"] = "DelphiBEAR"
    return True


def _header(profile: dict | None) -> None:
    color = (profile or {}).get("primary_color", "#6A0DAD")
    name = (profile or {}).get("name", st.session_state.get("username", "DelphiBEAR"))
    st.markdown(
        f"""
        <div class="dhc-header">
          <div>
            <p class="dhc-gold">Delphi Technologies</p>
            <h1 class="dhc-title" style="color:{color}">Delphi Command Center</h1>
            <p class="dhc-subtitle">Delphi: Home Control · Profile: {name} · 50-agent program</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _enabled_tabs(profile: dict | None) -> list:
    if not profile:
        return list(TAB_MODULES.keys())
    enabled = profile.get("enabled_tabs") or {}
    return [t for t in TAB_MODULES if enabled.get(t, True)]


def main() -> None:
    st.set_page_config(
        page_title="Delphi Command Center",
        page_icon="🧿",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "dark"

    st.markdown(get_theme_css(st.session_state.theme_mode, palette_for(None)), unsafe_allow_html=True)

    if not st.session_state.get("splash_done"):
        render_splash(True)
        time.sleep(2.9)
        st.session_state.splash_done = True
        st.rerun()
        return

    if not _login_gate():
        return

    if not st.session_state.get("dhc_hooks_ran"):
        hook_result = run_startup_hooks()
        st.session_state.agent_discovery = hook_result.get("discovery", {})
        st.session_state.phantom_status = verify_up_to_date()
        st.session_state.dhc_hooks_ran = True

    pid = st.session_state.get("active_profile_id")
    profile = load_profile(pid) if pid else None
    st.markdown(get_theme_css(st.session_state.theme_mode, palette_for(profile)), unsafe_allow_html=True)

    _header(profile)

    if "nav_page" not in st.session_state:
        st.session_state.nav_page = load_page()

    def _go(page: str) -> None:
        st.session_state.nav_page = save_page(page)
        st.rerun()

    keys = _enabled_tabs(profile)
    page = st.session_state.nav_page
    if page not in {"home", "settings"} and page not in keys:
        page = "home"
        st.session_state.nav_page = page

    with st.sidebar:
        st.markdown("### Session")
        st.write(st.session_state.get("username", ""))
        st.divider()
        day_mode = st.toggle(
            "Day mode",
            value=st.session_state.theme_mode == "light",
            help="Off = dark (default). On = day mode.",
        )
        new_mode = "light" if day_mode else "dark"
        if new_mode != st.session_state.theme_mode:
            st.session_state.theme_mode = new_mode
            st.rerun()
        st.caption(f"Theme: **{'Day' if new_mode == 'light' else 'Dark'}**")
        st.divider()
        if st.button("Home", key="nav_home", use_container_width=True):
            _go("home")
        if st.button("Settings", key="nav_settings", use_container_width=True):
            _go("settings")
        st.caption("Delphi: Home Control · local library")

    labels = {key: TAB_MODULES[key][0] for key in keys}
    if page == "home":
        front_page.render(profile, _go, keys, labels)
    elif page == "settings":
        app_settings.render(profile)
    else:
        if st.button("Back", key="nav_back"):
            _go("home")
        TAB_MODULES[page][1].render(profile)


if __name__ == "__main__":
    main()