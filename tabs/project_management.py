import os

import streamlit as st

from core.state import list_projects
from core.terminal_runner import is_allowed, run


def render(profile: dict | None) -> None:
    st.header("Project Management")
    st.caption("PR-03 — folder visualization + sandboxed terminal")

    projects = list_projects()
    if not projects:
        st.info("No projects yet. Use Central Command → Create Project.")
    else:
        pick = st.selectbox("Project", [p["name"] for p in projects])
        path = next(p["path"] for p in projects if p["name"] == pick)
        st.code(path)

        st.subheader("Folder tree")
        for root, dirs, files in os.walk(path):
            level = root.replace(path, "").count(os.sep)
            indent = "  " * level
            st.text(f"{indent}{os.path.basename(root)}/")
            for f in sorted(files)[:20]:
                st.text(f"{indent}  {f}")
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if level > 2:
                break

    st.divider()
    st.subheader("Terminal runner (allowlist)")
    cmd = st.text_input("Command", placeholder="git status")
    if st.button("Run") and cmd.strip():
        if not is_allowed(cmd):
            st.error("Command not in allowlist.")
        else:
            result = run(cmd, cwd=projects[0]["path"] if projects else None)
            st.code(result.stdout or result.stderr or "(no output)")
            if result.returncode != 0:
                st.caption(f"exit code: {result.returncode}")