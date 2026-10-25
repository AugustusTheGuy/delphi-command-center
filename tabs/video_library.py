import subprocess

import streamlit as st

from components.typeahead_bar import typeahead_bar
from core.media_archive import free_gb, nox_available
from core.media_index import build_video_index
from core.typeahead import rank_matches
from core.video_library import (
    STREAMING_SERVICES,
    ensure_video_extracted,
    finish_play,
    launch_streaming,
    most_watched_movies,
    play_vlc,
    shows_index,
)


def _play_row(row: dict) -> None:
    source = row.get("source")
    if source == "jellyfin":
        from core.media_services import load_media_services
        base = load_media_services()["jellyfin_url"].rstrip("/")
        if base and row.get("id"):
            subprocess.Popen(["open", f"{base}/web/index.html#!/details?id={row['id']}"], start_new_session=True)
            st.toast("Opened in Jellyfin")
        else:
            st.warning("Jellyfin is not connected.")
        return
    if source == "sonarr":
        st.info(row.get("path") or row.get("title"))
        return
    path = row.get("path")
    if path and not str(path).endswith(".zip"):
        ok, message = play_vlc(path, str(row.get("id")))
        st.success(message) if ok else st.error(message)
        return
    if row.get("kind") == "catalog":
        ok, _note, extracted = ensure_video_extracted(row)
        if ok and extracted:
            p_ok, p_msg = play_vlc(extracted, str(row.get("id")))
            st.success(p_msg) if p_ok else st.error(p_msg)
            return
    st.warning("Not on this Mac.")


def render(profile: dict | None) -> None:
    st.header("Video Library")
    if st.button("Refresh video list", key="video_refresh"):
        from core.media_index import clear_video_cache
        clear_video_cache()
        index, jellyfin_message = build_video_index(force=True)
    else:
        index, jellyfin_message = build_video_index()
    if jellyfin_message:
        st.caption(jellyfin_message)
    _left, center, _right = st.columns([2, 5, 2])
    with center:
        picked = typeahead_bar(index, key="video_typeahead")
        query = st.text_input("Filter", key="video_query", label_visibility="collapsed", placeholder="Search")
    if query:
        for hit in rank_matches(query, index, limit=10):
            label = f"{hit.get('title')} · {hit.get('source')}"
            if st.button(label, key=f"video_hit_{hit.get('id')}_{hit.get('source')}"):
                _play_row(hit)
    if isinstance(picked, dict) and picked.get("id"):
        nonce = picked.get("nonce")
        if nonce != st.session_state.get("video_pick_nonce"):
            st.session_state["video_pick_nonce"] = nonce
            match = next((row for row in index if row.get("id") == picked.get("id")), None)
            if match:
                _play_row(match)

    if not nox_available():
        st.warning("ExternalSSD not mounted — video archives require `/Volumes/ExternalSSD/DelphiMedia/Video/`.")
    else:
        st.caption(f"ExternalSSD free: **{free_gb():.1f} GB** · Movies/TV zips auto-extract on play, re-zip via hook")

    st.subheader("Streaming services")
    cols = st.columns(5)
    for i, svc in enumerate(STREAMING_SERVICES):
        with cols[i % 5]:
            if st.button(f"{svc['icon']}\n{svc['name']}", key=f"stream_{svc['name']}", use_container_width=True):
                ok, msg = launch_streaming(svc["url"])
                st.toast(msg) if ok else st.error(msg)

    st.divider()
    st.subheader("Most watched movies")
    movies = most_watched_movies()
    if not movies:
        st.caption("Add movie zips to `ExternalSSD/DelphiMedia/Video/Movies/archives/`")
    for movie in movies:
        c1, c2, c3 = st.columns([4, 1, 1])
        with c1:
            st.markdown(f"**{movie.get('title')}**")
        with c2:
            if movie.get("on_device") and st.button("▶ Play", key=f"mplay_{movie['id']}"):
                ok, _, path = ensure_video_extracted(movie)
                if ok and path:
                    p_ok, p_msg = play_vlc(path, movie["id"])
                    st.success(p_msg) if p_ok else st.error(p_msg)
        with c3:
            if st.button("📦", key=f"mrezip_{movie['id']}", help="Done watching — re-zip"):
                finish_play(movie["id"])
                st.toast("Re-zip hook ran")

    st.divider()
    st.subheader("TV shows")
    shows = shows_index()
    if not shows:
        st.caption("Add TV zips to `ExternalSSD/DelphiMedia/Video/TV/<Show>/Season_XX/<episode>.zip`")
    for show_name in sorted(shows.keys()):
        with st.expander(f"📺 {show_name}"):
            seasons: dict[str, list] = {}
            for ep in shows[show_name]:
                season = (ep.get("extra") or {}).get("season", "Season_01")
                seasons.setdefault(season, []).append(ep)
            picked_season = st.selectbox("Season", sorted(seasons.keys()), key=f"season_{show_name}")
            for ep in sorted(seasons.get(picked_season, []), key=lambda row: row.get("title", "")):
                ec1, ec2, ec3 = st.columns([4, 1, 1])
                ep_label = (ep.get("extra") or {}).get("episode", ep.get("title"))
                with ec1:
                    st.write(ep_label)
                with ec2:
                    if ep.get("on_device") and st.button("▶", key=f"tvplay_{ep['id']}"):
                        ok, _, path = ensure_video_extracted(ep)
                        if ok and path:
                            p_ok, p_msg = play_vlc(path, ep["id"])
                            st.success(p_msg) if p_ok else st.error(p_msg)
                with ec3:
                    if st.button("📦", key=f"tvrezip_{ep['id']}"):
                        finish_play(ep["id"])
                        st.toast("Re-zip hook ran")

    st.markdown(
        "**Local library only.** Place owned video files on ExternalSSD or the internal disk. "
        "Torrent/auto-download integrations are not supported."
    )
