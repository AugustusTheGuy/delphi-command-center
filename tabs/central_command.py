import streamlit as st

from core.multi_router import route_multi
from core.ollama_router import run_agent_prompt
from core.state import create_project, log_agent_task
from hooks.persistent_hooks import evaluate_context_hooks


def render(profile: dict | None) -> None:
    st.header("Central Command")
    st.caption("Multi-agent router — per-agent optimized prompts + persistent hooks")

    prompt_opt = st.checkbox("Prompt Optimization (prompt-master)", value=True)
    multi_agent = st.checkbox("Multi-agent fan-out", value=True, help="Route to all matching agents with tailored prompts")
    run_local = st.checkbox(
        "Run local Ollama",
        value=True,
        help="Execute routed prompts against installed Ollama models (Hermes, Qwen, Qwythos, Gemma).",
    )
    project_mode = st.checkbox("Project Prompt?")
    command = st.text_area("Enter command or voice transcript", height=120, placeholder="e.g. Forecast WiFi anomalies and check Home Assistant")

    if command.strip():
        context_hooks = evaluate_context_hooks(command)
        if context_hooks:
            with st.expander("Persistent hooks triggered", expanded=False):
                for h in context_hooks:
                    st.caption(f"**{h['hook']}** — {h['reason']}")

    if st.button("Execute", type="primary") and command.strip():
        routes = route_multi(command, use_optimizer=prompt_opt)
        if not multi_agent:
            routes = routes[:1]

        for r in routes:
            log_agent_task(
                r.agent_name,
                r.optimized_prompt[:120],
                "in_process",
                "hook" if r.is_hook else "agent",
            )
            st.success(f"Routed to **{r.agent_name}** (`{r.agent_id}`)")

            if run_local:
                with st.spinner(f"Running {r.agent_name} via Ollama…"):
                    outcome = run_agent_prompt(r.agent_id, r.optimized_prompt)
                if outcome.error:
                    st.error(outcome.error)
                    log_agent_task(r.agent_name, outcome.error[:120], "error", outcome.model or "ollama")
                elif outcome.skipped:
                    st.info(outcome.skip_reason)
                    log_agent_task(r.agent_name, outcome.skip_reason[:120], "skipped", "n/a")
                else:
                    st.markdown(f"**{r.agent_name}** · `{outcome.model}`")
                    st.write(outcome.response)
                    log_agent_task(
                        r.agent_name,
                        outcome.response[:120],
                        "completed",
                        outcome.model or "ollama",
                    )

            with st.expander(f"Prompt → {r.agent_name}"):
                st.write(r.optimized_prompt)
                if r.hook_payload:
                    st.caption("Hook payload")
                    st.json(r.hook_payload)

        if project_mode:
            pname = st.session_state.get("pending_project_name") or "QuickTask"
            create_project(pname)
            st.info(f"Project context: {pname}")

    st.divider()
    st.subheader("Installed agents")
    disc = st.session_state.get("agent_discovery")
    if disc:
        ready = [a["name"] for a in disc.get("agents", []) if a.get("installed")]
        st.caption(", ".join(ready) if ready else "Run discovery on startup.")
    else:
        st.caption("Discovery runs at DHC launch.")

    st.divider()
    st.subheader("Create / Open Project")
    c1, c2 = st.columns(2)
    with c1:
        new_name = st.text_input("New project name")
        if st.button("Create Project") and new_name.strip():
            path = create_project(new_name.strip())
            st.session_state["pending_project_name"] = new_name.strip()
            st.success(f"Created at `{path}`")
    with c2:
        from core.state import list_projects
        projects = list_projects()
        if projects:
            pick = st.selectbox("Open project", [p["name"] for p in projects])
            st.caption(next((p["path"] for p in projects if p["name"] == pick), ""))