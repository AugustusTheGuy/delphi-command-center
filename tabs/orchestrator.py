import streamlit as st

from core.agents_registry import agents_by_squad
from core.ollama_client import is_available, list_models
from core.state import log_agent_task

REGISTERED_AGENTS = [
    {"id": "planner", "role": "Delphi Planner", "model": "mlx-local", "status": "idle"},
    {"id": "coder", "role": "Code Executor", "model": "qwen2.5-coder", "status": "idle"},
    {"id": "home", "role": "Home Automator", "model": "crewai", "status": "idle"},
    {"id": "security", "role": "Security Monitor", "model": "gemma", "status": "idle"},
    {"id": "fable", "role": "Fable Agent (prompt persona)", "model": "ollama", "status": "idle"},
]


def render(profile: dict | None) -> None:
    st.header("AI Orchestrator")
    st.caption("CrewAI + MLX/Ollama harness — PR-02 live status")

    ollama_ok = is_available()
    models = list_models() if ollama_ok else []
    c1, c2 = st.columns(2)
    c1.metric("Ollama", "Online" if ollama_ok else "Offline")
    c2.metric("Models", str(len(models)))

    task = st.text_area("Crew task", placeholder="Research and draft Home Assistant setup for Samsung TVs")
    col1, col2 = st.columns(2)
    agents_pick = col1.multiselect(
        "Agents",
        [a["role"] for a in REGISTERED_AGENTS],
        default=["Delphi Planner", "Code Executor"],
    )
    model_choices = models or ["mlx-local", "ollama/gemma", "ollama/qwen2.5-coder"]
    model = col2.selectbox("Primary model", model_choices)

    if st.button("Launch Crew", type="primary") and task.strip():
        log_agent_task("CrewAI", task[:100], "in_process", model)
        st.success("Crew queued — Ollama routing active; full CrewAI wiring in PR-08.")
        with st.expander("Agent roster"):
            for a in REGISTERED_AGENTS:
                st.write(f"**{a['role']}** — {a['model']} ({a['status']})")

    st.divider()
    st.subheader("AI Core squad (50-agent program)")
    for a in agents_by_squad("AI Core"):
        st.caption(f"{a.name} · {a.pr} · {a.status}")

    st.subheader("Agent Designer")
    with st.form("new_agent"):
        role = st.text_input("Role name")
        tools = st.text_input("Tools (comma-separated)", "terminal,ha,nextcloud")
        submitted = st.form_submit_button("Register Agent")
        if submitted and role:
            st.success(f"Agent '{role}' registered locally.")