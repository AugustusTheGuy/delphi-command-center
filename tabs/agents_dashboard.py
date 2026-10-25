"""Agents Dashboard — 50-agent roster and PR assignment view."""

from __future__ import annotations

import streamlit as st

from core.agents_registry import AGENTS, agents_by_pr, summary_stats


def render(profile: dict | None) -> None:
    st.header("Agents Dashboard")
    st.caption("/agents · /agents-dashboard — full 50-agent program roster")

    stats = summary_stats()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total agents", stats["total"])
    c2.metric("Active", stats["active"])
    c3.metric("Idle", stats["idle"])
    c4.metric("Planned", stats["planned"])
    c5.metric("Blocked", stats["blocked"])

    squads = sorted({a.squad for a in AGENTS})
    prs = sorted({a.pr for a in AGENTS})

    view = st.radio("Group by", ["Squad", "PR", "All"], horizontal=True)
    filter_squad = st.selectbox("Filter squad", ["(all)"] + squads)
    filter_pr = st.selectbox("Filter PR", ["(all)"] + prs)
    search = st.text_input("Search agents", placeholder="e.g. Samsung, CrewAI, Ollama")

    rows = list(AGENTS)
    if filter_squad != "(all)":
        rows = [a for a in rows if a.squad == filter_squad]
    if filter_pr != "(all)":
        rows = [a for a in rows if a.pr == filter_pr]
    if search.strip():
        q = search.lower()
        rows = [a for a in rows if q in a.name.lower() or q in a.squad.lower() or q in a.model.lower()]

    if view == "Squad":
        for squad in squads:
            squad_rows = [a for a in rows if a.squad == squad]
            if not squad_rows:
                continue
            with st.expander(f"{squad} ({len(squad_rows)})", expanded=squad in ("AI Core", "Program")):
                for a in squad_rows:
                    _agent_row(a)
    elif view == "PR":
        for pr in prs:
            pr_rows = [a for a in rows if a.pr == pr]
            if not pr_rows:
                continue
            with st.expander(f"{pr} ({len(pr_rows)})"):
                for a in pr_rows:
                    _agent_row(a)
    else:
        for a in rows:
            _agent_row(a)

    st.divider()
    st.subheader("PR-02 → PR-06 execution lane")
    for pr in ("PR-02", "PR-03", "PR-04", "PR-05", "PR-06"):
        team = agents_by_pr(pr)
        active = sum(1 for t in team if t.status == "active")
        st.progress(min(active / max(len(team), 1), 1.0), text=f"{pr}: {active}/{len(team)} agents active")


def _agent_row(a) -> None:
    status_class = {
        "active": "dhc-status-ok",
        "idle": "dhc-status-warn",
        "planned": "dhc-status-warn",
        "blocked": "dhc-status-err",
    }.get(a.status, "dhc-status-warn")
    st.markdown(
        f"<div class='dhc-card'>"
        f"<b>{a.name}</b> <span class='{status_class}'>● {a.status}</span><br/>"
        f"<small>{a.id} · {a.squad} · {a.pr} · model: {a.model}</small>"
        f"</div>",
        unsafe_allow_html=True,
    )