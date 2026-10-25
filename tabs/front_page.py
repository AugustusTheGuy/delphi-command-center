"""Front page. Big choices, a short setup list, and the other pages under More."""

from __future__ import annotations

import streamlit as st

from core.ai_status import local_ai_line
from core.log_view import server_log_text
from core.setup_status import setup_status

BIG = (
    ("video_library", "Video"),
    ("home_management", "House"),
)


def render_trouble() -> None:
    if st.button("What went wrong", key="trouble_btn"):
        st.session_state["show_server_log"] = True
    if st.session_state.get("show_server_log"):
        st.code(server_log_text(), language="text")


def render(profile: dict | None, go, enabled: list[str], labels: dict[str, str]) -> None:
    del profile
    st.markdown(
        """
        <style>
        div[class*="st-key-home_"] button {
          min-height: 96px;
          font-size: 1.7rem;
          font-weight: 700;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    line = local_ai_line()
    if line:
        st.caption(line)
    left, right = st.columns(2)
    slots = (left, right, left, right)
    for (page, label), column in zip(BIG, slots):
        if page not in enabled:
            continue
        with column:
            if st.button(label, key=f"home_{page}", use_container_width=True):
                go(page)
    st.subheader("Setup")
    for row in setup_status():
        state = "Ready" if row["ok"] else "Needs a look"
        st.write(f"**{row['label']}** — {state}. {row['detail']}")
    render_trouble()
    more = [key for key in enabled if key not in {page for page, _label in BIG}]
    if more:
        with st.expander("More"):
            for key in more:
                if st.button(labels.get(key, key), key=f"more_{key}", use_container_width=True):
                    go(key)
