import streamlit as st

from core.github_suggestions import enrich_github, list_hf


def render(profile: dict | None) -> None:
    st.header("GitHub & HuggingFace Additions")
    st.caption("PR-06 — dynamic GitHub star counts + curated HF models")

    refresh = st.button("Refresh GitHub stars")
    g, h = st.columns(2)
    with g:
        st.subheader("GitHub — System")
        for item in enrich_github():
            stars = item.get("stars")
            star_txt = f" ★ {stars:,}" if stars is not None else ""
            st.markdown(f"**{item['name']}**{star_txt} — {item['desc']}")
            st.caption(f"github.com/{item['repo']}")
    with h:
        st.subheader("HuggingFace — Models/Tools")
        for item in list_hf():
            st.markdown(f"**{item['name']}** — {item['desc']}")
            st.caption(f"huggingface.co/{item['model_id']}")

    if refresh:
        st.rerun()