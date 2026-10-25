import streamlit as st

from core.state import get_operations, log_operation


def render(profile: dict | None) -> None:
    st.header("OS Management")
    st.caption("PR-05 — tracked changes with reversal safety checks")

    with st.expander("Log a change"):
        title = st.text_input("Change title")
        impact = st.text_area("Initial impact")
        if st.button("Record change") and title and impact:
            log_operation(title, impact, impact)
            st.success("Logged.")
            st.rerun()

    ops = get_operations()
    if not ops:
        st.info("No completed operations yet.")
        return

    for op in ops:
        with st.expander(op["title"]):
            st.write(f"**Initial:** {op['initial_impact']}")
            st.write(f"**Current:** {op['current_impact']}")
            if op.get("reversible") and st.button("Reverse", key=f"rev_{op['id']}"):
                st.warning(
                    "Reversal preview: restores prior state. "
                    "Confirm in terminal before destructive rollback (PR-05 safety gate)."
                )