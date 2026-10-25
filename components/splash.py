"""Launch splash. The Mac app plays macos/splash.html over the whole window.

A browser that opens the page directly gets the same screen once.
prefers-reduced-motion hides the sequence, including the flash.
"""

from pathlib import Path

import streamlit as st

SPLASH_SECONDS = 6.7
SPLASH_PATH = Path(__file__).resolve().parent.parent / "macos" / "splash.html"
SPLASH_MARKUP = SPLASH_PATH.read_text(encoding="utf-8")


def render_splash(show: bool = True) -> None:
    if not show:
        return
    st.markdown(SPLASH_MARKUP, unsafe_allow_html=True)
