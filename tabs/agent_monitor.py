import streamlit as st

from core.state import get_agent_tasks


def render(profile: dict | None) -> None:
    st.header("Agent Monitor")
    data = get_agent_tasks()

    st.subheader("Active")
    if not data.get("active"):
        st.info("No active tasks.")
    for t in data.get("active", []):
        st.markdown(
            f"<div class='dhc-card'><b>{t.get('agent')}</b> — {t.get('task')} "
            f"<span class='dhc-status-warn'>● {t.get('status')}</span></div>",
            unsafe_allow_html=True,
        )

    st.subheader("Terminal tasks")
    st.caption("Completed / in-process shell operations appear here with Central Command.")

    for period, label in [("24h", "Last 24 hours"), ("7d", "Last 7 days"), ("30d", "Last 30 days")]:
        with st.expander(label):
            shown = 0
            for h in data.get("history", []):
                if shown >= 15:
                    break
                st.write(f"**{h.get('agent')}** · {h.get('task')[:80]} · `{h.get('language', '')}`")
                shown += 1
            if shown == 0:
                st.caption("No history yet.")