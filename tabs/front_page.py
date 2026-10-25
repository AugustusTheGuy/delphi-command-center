"""Front page. Four choices, then what still needs a setup step."""

from __future__ import annotations

import html

import streamlit as st

from core.ai_status import local_ai_line
from core.log_view import server_log_text
from core.setup_status import setup_status

CHOICES = (
    ("video_library", "Video", "Movies and shows already on this Mac.", "secondary"),
    ("home_management", "House", "Rooms and lights.", "secondary"),
)


def render_trouble() -> None:
    if st.button("What went wrong", key="trouble_btn"):
        st.session_state["show_server_log"] = True
    if st.session_state.get("show_server_log"):
        st.code(server_log_text(), language="text")


def render(profile: dict | None, go, enabled: list[str], labels: dict[str, str]) -> None:
    del profile
    line = local_ai_line()
    if line:
        st.caption(line)
    left, right = st.columns(2)
    slots = (left, right, left, right)
    for (page, label, blurb, kind), column in zip(CHOICES, slots):
        if page not in enabled:
            continue
        with column:
            if st.button(label, key=f"home_{page}", type=kind, width="stretch"):
                go(page)
            st.markdown(f"<p class='dhc-choice'>{html.escape(blurb)}</p>", unsafe_allow_html=True)
    st.subheader("Setup")
    for row in setup_status():
        kind = "ok" if row["ok"] else "idle"
        state = "Ready" if row["ok"] else "Needs a look"
        label = html.escape(str(row["label"]))
        detail = html.escape(str(row["detail"]))
        st.markdown(
            f"<p class='dhc-setup'><span class='dhc-status-{kind}'>{label}</span>"
            f" · {state}. {detail}</p>",
            unsafe_allow_html=True,
        )
    render_trouble()
    shown = {page for page, _label, _blurb, _kind in CHOICES}
    more = [key for key in enabled if key not in shown]
    if more:
        with st.expander("More"):
            for key in more:
                if st.button(labels.get(key, key), key=f"more_{key}", width="stretch"):
                    go(key)
