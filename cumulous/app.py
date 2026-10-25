"""Cumulous Mac shell — Apple Account → devices, CardSession-grade minimal UI."""

from __future__ import annotations

import html
import time
from datetime import datetime

import streamlit as st

from cumulous import PRODUCT_NAME, __version__
from cumulous.action_status import get_status, set_status
from cumulous.apple_accounts import (
    catalog_by_apple_account,
    ensure_account_2fa,
    get_account_2fa_secret,
    list_accounts,
    migrate_devices_to_primary_apple_account,
    read_2xsecrets_for_ceo,
    sync_scraped_accounts,
    verify_account_2fa,
)
from cumulous.auth import bearaccount_exists, load_secrets
from cumulous.backup_ops import restore_to_mac, secure_backup_device
from cumulous.ceo_override import write_ceo_override_md
from cumulous.challenge_codes import (
    spawn_challenge_for_apple_account,
    spawn_challenge_for_user,
    verify_challenge,
)
from cumulous.devices import (
    attempt_pair,
    device_inventory,
    probe_connected_device,
    register_device,
)
from cumulous.install_invite import (
    auto_invite_connected_device,
    best_app_url,
    best_portal_url,
    create_invite_for_device,
    invite_all_apple_account_devices,
    try_usb_install_ipa,
)
from cumulous.network_backup import backup_endpoints, enable_wifi_sync_hint, load_network_prefs, save_network_prefs
from cumulous.paths import externalssd_mounted, restore_export_root, vault_root
from cumulous.photo_offload import load_prefs as load_photo_prefs, record_setup_choice, save_prefs as save_photo_prefs
from cumulous.setup_tools import ensure_libimobiledevice, status_report
from cumulous.splash import render_splash
from cumulous.ui_feedback import (
    clear_flashes,
    inject_modal_css,
    push_macos_native_code,
    push_macos_success,
    queue_flash,
    render_action_badge,
    render_flashes,
    sheet_ok,
    toast_fail,
    toast_ok,
)
from cumulous.ux_copy import friendly_message

DEFAULT_LOCATION = "This Mac Mini · Cumulous Cloud"


def _bootstrap() -> None:
    st.set_page_config(
        page_title=f"{PRODUCT_NAME} Cloud",
        page_icon="☁️",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    inject_modal_css(st)


def _flash_ok(title: str, detail: str = "", *, minor: bool = True) -> None:
    """Apple-like feedback: minor → quiet toast; major → primary sheet.

    Never pass raw dicts, paths, digests, or codes — only short plain English.
    """
    plain = friendly_message(title, fallback=title or "Completed")
    body = friendly_message(detail, fallback=detail or "", allow_empty=True)
    # Strip accidental technical leftovers
    if body and any(x in body for x in ("/", "{", "}", "0x", "Traceback")):
        body = ""
    if minor:
        toast_ok(st, plain, body)
    else:
        sheet_ok(st, plain, body)
        push_macos_success(plain)


def _soft_note(title: str, detail: str = "") -> None:
    """Quiet failure / heads-up — never terminal dumps, never full-screen modal."""
    toast_fail(
        st,
        friendly_message(title, fallback="Couldn’t finish"),
        friendly_message(detail, fallback=detail or "", allow_empty=True),
    )


def _badge_only(action_id: str, status: str, message: str, detail: str = "") -> None:
    """Inline status only — no toast/sheet (iOS pattern for minor actions)."""
    set_status(
        action_id,
        status,
        message=friendly_message(message, fallback=message or ""),
        detail=friendly_message(detail, fallback=detail or "", allow_empty=True) if detail else "",
    )


def _flash_code(
    code: str,
    *,
    title: str = "Confirm 4-Digit Code",
    instructions: str = "",
    fanout_summary: str = "",
    dialog: str = "confirm",  # confirm | backup | none
) -> None:
    """Open ONE delivery sheet (map + code); phones get the same payload via poll/USB."""
    from cumulous.challenge_push import challenge_card_html, latest_active_code
    from cumulous.device_location import resolve_challenge_location

    loc = resolve_challenge_location(prefer_fresh_ip=True)
    place = loc.get("display_place") or DEFAULT_LOCATION
    map_url = loc.get("map_url") or ""
    live = latest_active_code() or {}
    if (live.get("location") or {}).get("map_url"):
        map_url = live["location"]["map_url"]
        place = live["location"].get("display_place") or place
    st.session_state["last_challenge_card_html"] = challenge_card_html(
        code,
        purpose=title,
        place=place,
        map_url=map_url,
        seconds_left=int(live.get("seconds_left") or 30 * 60),
        title="Confirm 4-Digit Code",
    )
    st.session_state["last_challenge_map_url"] = map_url
    st.session_state["last_challenge_place"] = place
    # Quiet flash only — no second modal from toast stack
    queue_flash(
        st,
        "toast",
        "Confirm 4-Digit Code",
        instructions
        or f"Code sent once to {fanout_summary or 'your Apple devices'}. Map shows request location.",
        priority="toast",
        auto_dismiss_sec=3.5,
    )
    push_macos_native_code(code, title="Confirm 4-Digit Code")
    if dialog == "confirm":
        st.session_state["confirm_delivery_open"] = True
        st.session_state["confirm_dialog_open"] = False
        st.session_state["confirm_input_open"] = False
    elif dialog == "backup":
        st.session_state["backup_dialog_open"] = True


def _dismiss_confirm_dialog(*, cancel_flow: bool = False, show_input: bool = False) -> None:
    """Close delivery sheet. Optionally open centered pin-entry (does not cancel flow)."""
    clear_flashes(st)
    st.session_state["confirm_dialog_open"] = False
    st.session_state["confirm_delivery_open"] = False
    st.session_state.pop("confirm_dialog_code_display", None)
    if show_input:
        st.session_state["confirm_input_open"] = True
    if cancel_flow:
        st.session_state.pop("confirm_flow", None)
        st.session_state.pop("confirm_code_shown", None)
        st.session_state["confirm_input_open"] = False


def _ensure_challenge_map() -> tuple[str, str]:
    """Return (map_url, place); regenerate if missing so map always loads."""
    map_url = st.session_state.get("last_challenge_map_url") or ""
    place = st.session_state.get("last_challenge_place") or ""
    if map_url and place:
        return map_url, place
    try:
        from cumulous.challenge_push import latest_active_code
        from cumulous.device_location import resolve_challenge_location

        live = latest_active_code() or {}
        loc = live.get("location") or {}
        map_url = loc.get("map_url") or live.get("map_url") or map_url
        place = loc.get("display_place") or live.get("display_place") or place
        if not map_url:
            fresh = resolve_challenge_location(prefer_fresh_ip=True)
            map_url = fresh.get("map_url") or fresh.get("map_url_2x") or ""
            place = place or fresh.get("display_place") or DEFAULT_LOCATION
        st.session_state["last_challenge_map_url"] = map_url
        st.session_state["last_challenge_place"] = place or DEFAULT_LOCATION
    except Exception:
        place = place or DEFAULT_LOCATION
    return map_url, place or DEFAULT_LOCATION


@st.dialog("Confirm 4-Digit Code", width="small")
def _confirm_delivery_dialog() -> None:
    """Phase 1 — delivery: digits + live map (~⅓) + Apple-blue Input Code (bottom-right)."""
    flow = st.session_state.get("confirm_flow") or {}
    fanout = flow.get("fanout_labels") or flow.get("fanout") or []
    fanout_txt = ", ".join(str(x) for x in fanout[:8]) if fanout else "your linked Apple devices"
    map_url, place = _ensure_challenge_map()
    code = ""
    try:
        from cumulous.challenge_push import latest_active_code

        live = latest_active_code() or {}
        code = str(live.get("code") or "")
    except Exception:
        pass
    digits = "".join(c for c in code if c.isdigit())[:4]
    boxes = (
        "".join(f'<span class="cs-pin-box">{d}</span>' for d in digits.zfill(4))
        if len(digits) == 4
        else '<div class="cs-pin-boxes-hidden">See your iPhone</div>'
    )
    # Cache-bust map so it always reloads fully
    map_src = html.escape(map_url)
    if map_url and "staticmap" in map_url:
        map_src = html.escape(map_url + ("&" if "?" in map_url else "?") + "cb=1")
    map_html = (
        f'<div class="cs-pin-map-wrap cs-pin-map-third">'
        f'<img class="cs-pin-map" src="{map_src}" alt="Device location" '
        f'width="280" height="130" loading="eager" decoding="sync" '
        f'referrerpolicy="no-referrer" onerror="this.style.opacity=0.4"/></div>'
        if map_url
        else '<div class="cs-pin-map-wrap cs-pin-map-third cs-pin-map-empty">Map loading…</div>'
    )
    st.markdown(
        """
<style>
div[data-testid="stDialog"] { max-width: 300px !important; }
/* Glassy Apple blue for Input Code — inherits shine from global primary styles */
div[data-testid="stDialog"] button[kind="primary"] {
  border-radius: 12px !important; font-weight: 600 !important;
}
div[data-testid="stDialog"] button[kind="secondary"] {
  background: transparent !important; color: #8e8e93 !important; border: none !important;
}
</style>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
<div class="cs-pin-card"><div class="cs-pin-card-inner">
  <div class="cs-pin-title">Confirm 4-Digit Code</div>
  <div class="cs-pin-sub">Pushed to all linked devices · one code only</div>
  <div class="cs-pin-boxes">{boxes}</div>
  <div class="cs-pin-place">{html.escape(str(place))}</div>
  {map_html}
  <div class="cs-pin-ttl">Devices: {html.escape(fanout_txt)}</div>
</div></div>
""",
        unsafe_allow_html=True,
    )
    # Bottom row: Cancel left · Input Code right (Apple blue)
    left, right = st.columns([1, 1.15])
    with left:
        if st.button("Cancel", type="secondary", use_container_width=True, key="dlg_delivery_cancel"):
            _dismiss_confirm_dialog(cancel_flow=True)
            st.rerun()
    with right:
        if st.button("Input Code", type="primary", use_container_width=True, key="dlg_input_code"):
            # Close delivery → open input mini-window (same size, centered)
            _dismiss_confirm_dialog(cancel_flow=False, show_input=True)
            st.rerun()


@st.dialog("Confirm 4-Digit Code", width="small")
def _confirm_input_dialog() -> None:
    """Phase 2 — after Input Code: 4-digit textbox, same card size, centered."""
    flow = st.session_state.get("confirm_flow") or {}
    map_url, place = _ensure_challenge_map()
    map_html = (
        f'<div class="cs-pin-map-wrap cs-pin-map-third">'
        f'<img class="cs-pin-map" src="{html.escape(map_url)}" alt="map" '
        f'loading="eager" decoding="sync" referrerpolicy="no-referrer"/></div>'
        if map_url
        else ""
    )
    st.markdown(
        """
<style>
div[data-testid="stDialog"] { max-width: 300px !important; }
div[data-testid="stDialog"] input[type="text"] {
  max-width: 7.5rem !important; width: 7.5rem !important;
  font-size: 1.55rem !important; letter-spacing: 0.42em !important;
  text-align: center !important; font-weight: 600 !important;
  font-variant-numeric: tabular-nums !important;
}
div[data-testid="stDialog"] [data-testid="stTextInput"] {
  display: flex; justify-content: center;
}
div[data-testid="stDialog"] button[kind="primary"] {
  border-radius: 12px !important; font-weight: 600 !important;
}
</style>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
<div class="cs-pin-card"><div class="cs-pin-card-inner">
  <div class="cs-pin-title">Confirm 4-Digit Code</div>
  <div class="cs-pin-sub">Enter the code from your devices</div>
  <div class="cs-pin-place">{html.escape(str(place))}</div>
  {map_html}
</div></div>
""",
        unsafe_allow_html=True,
    )
    code_in = st.text_input(
        "4-digit code",
        max_chars=4,
        key="confirm_dialog_4digit",
        placeholder="••••",
        label_visibility="collapsed",
    )
    left, right = st.columns([1, 1.15])
    with left:
        if st.button("Cancel", type="secondary", use_container_width=True, key="dlg_cancel_4"):
            _dismiss_confirm_dialog(cancel_flow=True)
            st.rerun()
    with right:
        if st.button("Verify", type="primary", use_container_width=True, key="dlg_verify_4"):
            set_status("confirm_user", "running", message="Checking code…")
            if verify_challenge(code_in, purpose="confirm_user"):
                flow["step"] = "totp"
                st.session_state["confirm_flow"] = flow
                st.session_state["confirm_input_open"] = False
                st.session_state["confirm_dialog_open"] = False
                clear_flashes(st)
                set_status("confirm_user", "ok", message="Verified")
                _flash_ok("Verified", "Enter 2FA next.")
                st.rerun()
            else:
                set_status("confirm_user", "error", message="Code not accepted")
                _soft_note("Code not accepted", "Request a new code and try again.")


def _dismiss_backup_auth_dialog() -> None:
    clear_flashes(st)
    st.session_state.pop("backup_auth", None)
    st.session_state.pop("backup_dialog_open", None)
    st.session_state.pop("backup_dialog_code_display", None)
    set_status("backup_auth", "idle", message="")


@st.dialog("Backup Authorization", width="large")
def _backup_auth_dialog() -> None:
    """Entry-only: code lives on phone — never shown in this window."""
    auth = st.session_state.get("backup_auth") or {}
    labels = auth.get("fanout_labels") or auth.get("fanout") or []
    fanout_txt = ", ".join(str(x) for x in labels[:10]) if labels else "your Apple devices"

    st.markdown(
        """
<style>
button[title="Close window"] {
  background: #ff5f57 !important; color: transparent !important;
  border: 0.5px solid #e0443e !important; border-radius: 50% !important;
  min-height: 14px !important; height: 14px !important;
  max-width: 14px !important; width: 14px !important; min-width: 14px !important;
  padding: 0 !important; font-size: 0 !important; box-shadow: none !important;
}
button[title="Close window"]:hover { background: #ff453a !important; }
div[data-testid="stDialog"] input[type="text"] {
  max-width: 7.25rem !important; width: 7.25rem !important;
  font-size: 1.65rem !important; letter-spacing: 0.35em !important;
  text-align: center !important; font-weight: 600 !important;
  font-variant-numeric: tabular-nums !important; padding: 0.65rem 0.5rem !important;
}
div[data-testid="stDialog"] [data-testid="stTextInput"] {
  display: flex; justify-content: center;
}
</style>
""",
        unsafe_allow_html=True,
    )
    tl, _ = st.columns([1, 10])
    with tl:
        if st.button("×", key="bak_dlg_red_close", help="Close window", use_container_width=True):
            _dismiss_backup_auth_dialog()
            st.rerun()

    st.markdown(
        f"<div style='text-align:center'>"
        f"<div style='font-size:1.05rem;font-weight:600;letter-spacing:-0.02em;margin-bottom:0.45rem'>Enter code</div>"
        f"<div style='font-size:0.85rem;color:#8e8e93;line-height:1.4;margin-bottom:1rem'>"
        f"Sent to <b style='color:#f5f5f7'>{html.escape(fanout_txt)}</b>. "
        f"Not shown on this Mac window.</div></div>",
        unsafe_allow_html=True,
    )

    code_in = st.text_input(
        "4-digit authorization",
        max_chars=4,
        key="bak_dialog_4digit",
        placeholder="••••",
        label_visibility="collapsed",
    )
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Verify & continue", type="primary", use_container_width=True, key="bak_dlg_verify"):
            if verify_challenge(code_in, purpose="backup_request"):
                auth["code_ok"] = True
                st.session_state["backup_auth"] = auth
                st.session_state["backup_dialog_open"] = False
                clear_flashes(st)
                set_status("backup_auth", "ok", message="Authorized")
                _flash_ok("Backup authorized")
                st.rerun()
            else:
                set_status("backup_auth", "error", message="Code not accepted")
                _soft_note("Code not accepted", "Request a new code and try again.")
    with b2:
        if st.button("Cancel", use_container_width=True, key="bak_dlg_cancel"):
            _dismiss_backup_auth_dialog()
            st.rerun()


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%b %d, %Y · %I:%M %p")
    except Exception:
        return "—"


def _primary_apple_id() -> str:
    accs = list_accounts()
    for a in accs:
        if a.get("is_ceo"):
            return a["apple_id"]
    if accs:
        return accs[0]["apple_id"]
    scraped = sync_scraped_accounts()
    return scraped[0]["apple_id"] if scraped else ""


def _esc_button(key: str) -> bool:
    """In-tab red ESC (glassy, −15% size). Traffic-light chrome stays full size."""
    # Styling lives in ui_feedback inject_modal_css:
    # button[kind="secondary"][title="Cancel and close"]
    return st.button("ESC", key=key, type="secondary", help="Cancel and close")


def _render_photos_tab() -> None:
    """Photos.app-like library: days grid, search, deep tags. Mac viewer for dual-mirrored media."""
    from cumulous.photo_library import albums_by_day, albums_summary, display_policy, list_assets, scan_library

    st.markdown(
        "<div class='cs-header'>Photos</div>"
        "<div class='cs-muted' style='margin-bottom:0.75rem'>"
        "Apple’s Photos app <b>cannot</b> show Mac/HDD backups as iCloud placeholders. "
        "Cumulous Photos is the in-app library — same originals on every device, "
        "with <b>deeper tagging</b> (date, place, people, plants, objects, setting, context)."
        "</div>",
        unsafe_allow_html=True,
    )
    policy = display_policy()
    st.caption(policy.get("tagging_upgrade") or "")

    t1, t2, t3 = st.columns([2, 1, 1])
    with t1:
        q = st.text_input(
            "Search tags, places, people, context",
            value=st.session_state.get("photos_q") or "",
            key="photos_q_input",
            placeholder="beach · kitchen · birthday · plant · person…",
        )
        st.session_state["photos_q"] = q
    with t2:
        if st.button("Refresh library", use_container_width=True, key="photos_scan"):
            set_status("photos_scan", "running", message="Scanning…")
            res = scan_library(enrich=True)
            n = int(res.get("count") or 0)
            _badge_only("photos_scan", "ok", f"{n} photos", "Library refreshed")
            st.rerun()
        render_action_badge(st, "photos_scan")
    with t3:
        view_mode = st.selectbox("View", ["Days", "All", "Albums"], key="photos_view_mode")

    # Photo backup lifecycle strip
    from cumulous.photo_offload import (
        freeable_on_device,
        harvest_progress,
        load_prefs as _photo_prefs_live,
        start_device_media_harvest,
        usb_device_present,
    )

    ph_prefs = _photo_prefs_live()
    hprog = harvest_progress()
    harv = hprog.get("harvest") or {}
    usb = usb_device_present()
    free_n = len(freeable_on_device(dual_only=True))
    lib_n = int((hprog.get("library") or {}).get("file_count") or 0)
    dual_n = int((hprog.get("library") or {}).get("dual_mirrored") or 0)
    inv_n = int((hprog.get("device_inventory") or {}).get("media_total") or 0)
    st.markdown(
        f"<div class='cs-card' style='margin-bottom:0.75rem'>"
        f"<div class='cs-header'>On-device backup</div>"
        f"<b>{lib_n}</b> in Cumulous · <b>{dual_n}</b> dual-mirrored"
        f"{(f' · ~{inv_n} on phone (USB count)' if inv_n else '')}"
        f"<br><span class='cs-muted'>"
        f"{'USB connected' if usb.get('usb') else 'USB not connected — plug in to back up or free phone space from this Mac'}"
        f" · {free_n} freeable on phone after dual-verify"
        f"</span>"
        f"{('<br><span class=\"cs-status-ok\">● Backing up… '
            + str(harv.get('mirrored') or 0) + ' new · skipped '
            + str(harv.get('skipped_existing') or 0) + '</span>') if harv.get('status') == 'running' else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )
    pb1, pb2, pb3 = st.columns(3)
    with pb1:
        if st.button("Backup all on-device photos", type="primary", use_container_width=True, key="photos_harvest_usb"):
            if not usb.get("usb"):
                _soft_note("Connect iPhone", "Plug in with USB, unlock, and tap Trust.")
            else:
                probe = usb.get("probe") or {}
                did = probe.get("imei") or probe.get("device_id") or probe.get("udid") or ""
                set_status("media_harvest", "running", message="Backing up photos…")
                start_device_media_harvest(
                    device_id=str(did),
                    udid=str(probe.get("udid") or ""),
                    apple_account_id=_primary_apple_id() or "",
                    limit=None,
                )
                _flash_ok("Photo backup started", "Running in the background — keep the cable connected.")
            st.rerun()
    with pb2:
        keep_on = bool(ph_prefs.get("download_and_keep_originals"))
        if st.button(
            "Download & Keep Originals: ON" if keep_on else "Download & Keep Originals: OFF",
            use_container_width=True,
            key="photos_keep_orig",
            disabled=not ph_prefs.get("initial_backup_complete") and dual_n < 1,
            help="After the first full backup, turn on to keep new originals on the phone while still adding them to Cumulous.",
        ):
            from cumulous.photo_offload import set_download_and_keep_originals

            set_download_and_keep_originals(not keep_on)
            _badge_only(
                "photos_keep",
                "ok",
                "Keep originals on" if not keep_on else "Keep originals off",
            )
            st.rerun()
        render_action_badge(st, "photos_keep")
    with pb3:
        if st.button("Remove Photo Backup", use_container_width=True, key="photos_rm_all"):
            st.session_state["confirm_rm_all_photos"] = True
            st.rerun()
    if st.session_state.get("confirm_rm_all_photos"):
        st.warning(
            "This removes dual-backed-up photos from the iPhone only. "
            "They stay in Cumulous on this Mac. USB required."
        )
        cya, cyb = st.columns(2)
        with cya:
            if st.button("Yes, free phone space", type="primary", key="photos_rm_all_yes"):
                from cumulous.photo_offload import request_device_delete_all_freeable

                res = request_device_delete_all_freeable(source="mac", execute_afc=True)
                st.session_state.pop("confirm_rm_all_photos", None)
                if res.get("ok"):
                    _flash_ok(
                        "Phone cleanup done",
                        res.get("message") or f"{res.get('removed', 0)} removed",
                        minor=False,
                    )
                else:
                    _soft_note("Couldn’t free space", res.get("message") or "Plug in the iPhone with USB.")
                st.rerun()
        with cyb:
            if st.button("Cancel", key="photos_rm_all_no"):
                st.session_state.pop("confirm_rm_all_photos", None)
                st.rerun()
    render_action_badge(st, "media_harvest")

    albums = albums_summary()
    acols = st.columns(min(6, max(1, len(albums))))
    for i, alb in enumerate(albums[:6]):
        with acols[i]:
            st.markdown(
                f"<div class='cs-card' style='padding:10px;text-align:center'>"
                f"<div style='font-size:0.75rem;opacity:.7'>{alb.get('title')}</div>"
                f"<div style='font-size:1.1rem;font-weight:600'>{alb.get('count', 0)}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    if view_mode == "Albums":
        for alb in albums:
            st.markdown(f"**{alb.get('title')}** · {alb.get('count', 0)}")
        return

    if view_mode == "All" or q:
        res = list_assets(query=q or "", limit=240, sort="date_desc")
        items = res.get("items") or []
        st.caption(f"{res.get('total', 0)} in library · showing {len(items)} previews")
        _render_photo_grid(items, max_n=240)
    else:
        days = albums_by_day(limit_days=45)
        if not days:
            st.markdown(
                "<div class='cs-card cs-muted'>No photos in the library yet. "
                "Run a backup or offload, then refresh.</div>",
                unsafe_allow_html=True,
            )
        else:
            for day in days:
                title = day.get("title") or day.get("id")
                sub = day.get("subtitle") or ""
                st.markdown(
                    f"<div style='margin:1rem 0 0.4rem;font-weight:600;font-size:1.05rem'>{title}"
                    f"<span class='cs-muted' style='font-weight:400;font-size:0.9rem'> · {day.get('count', 0)}"
                    f"{(' · ' + sub) if sub else ''}</span></div>",
                    unsafe_allow_html=True,
                )
                _render_photo_grid(day.get("items") or [], max_n=48)

    # Full preview lightbox (Mac red close + click outside)
    if st.session_state.get("photos_selected"):
        _render_photo_lightbox()


def _fmt_tag_list(items: list | None) -> str:
    if not items:
        return "—"
    labels = []
    for x in items:
        if isinstance(x, dict):
            labels.append(str(x.get("label") or x))
        else:
            labels.append(str(x))
    return ", ".join(labels) if labels else "—"


def _close_photo_viewer() -> None:
    st.session_state.pop("photos_selected", None)
    st.session_state.pop("photos_lightbox_open", None)
    st.session_state.pop("photo_dlg_show_details", None)


@st.dialog("Preview", width="large")
def _photo_lightbox_dialog() -> None:
    """Mac-style photo/video preview: red close top-left, dismiss by closing dialog."""
    from cumulous.photo_library import preview_kind, resolve_media_path, thumb_bytes
    from cumulous.photo_tagging import get_tags

    dig = st.session_state.get("photos_selected") or ""
    if not dig:
        st.session_state.pop("photos_lightbox_open", None)
        return

    st.markdown(
        """
<style>
button[title="Close window"] {
  background: #ff5f57 !important; color: transparent !important;
  border: 0.5px solid #e0443e !important; border-radius: 50% !important;
  min-height: 14px !important; height: 14px !important;
  max-width: 14px !important; width: 14px !important; min-width: 14px !important;
  padding: 0 !important; font-size: 0 !important; box-shadow: none !important;
}
button[title="Close window"]:hover { background: #ff453a !important; }
div[data-testid="stDialog"] img { border-radius: 12px; max-height: 62vh; object-fit: contain; }
</style>
""",
        unsafe_allow_html=True,
    )
    top, _ = st.columns([1, 12])
    with top:
        if st.button("×", key="photo_dlg_red_close", help="Close window", use_container_width=True):
            _close_photo_viewer()
            st.rerun()

    kind = preview_kind(dig)
    path = resolve_media_path(dig)

    # Photo only — no metadata until user opens details (iOS Photos pattern)
    if kind == "video" and path and path.is_file():
        try:
            st.video(str(path))
        except Exception:
            data = thumb_bytes(dig)
            if data:
                st.image(data, use_container_width=True)
    else:
        data = thumb_bytes(dig)
        if data:
            st.image(data, use_container_width=True)
        elif path and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}:
            try:
                st.image(str(path), use_container_width=True)
            except Exception:
                st.caption("Preview unavailable — file is in the vault.")
        else:
            st.caption("Preview unavailable")

    show_details = st.session_state.get("photo_dlg_show_details") is True
    d1, d2 = st.columns(2)
    with d1:
        if st.button(
            "Hide details" if show_details else "Show details",
            use_container_width=True,
            key="photo_dlg_toggle_details",
        ):
            st.session_state["photo_dlg_show_details"] = not show_details
            st.rerun()
    with d2:
        if st.button("Done", type="primary", use_container_width=True, key="photo_dlg_done"):
            st.session_state.pop("photo_dlg_show_details", None)
            _close_photo_viewer()
            st.rerun()

    if show_details:
        tags = get_tags(dig) or {}
        loc = tags.get("location") or {}
        st.markdown(
            f"<div class='cs-muted' style='font-size:0.85rem;line-height:1.45;margin-top:0.75rem'>"
            f"<b style='color:#f5f5f7'>When</b> {html.escape(str(tags.get('captured_at_iso') or '—'))} · "
            f"<b style='color:#f5f5f7'>Where</b> {html.escape(str(loc.get('place_name') or loc.get('city') or '—'))}<br>"
            f"<b style='color:#f5f5f7'>Setting</b> {html.escape(str(tags.get('setting') or '—'))} · "
            f"<b style='color:#f5f5f7'>Context</b> {html.escape(str(tags.get('context') or '—'))}"
            f"</div>",
            unsafe_allow_html=True,
        )
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Deep re-tag", use_container_width=True, key="photo_dlg_enrich"):
                from cumulous.photo_library import re_enrich_digest

                r = re_enrich_digest(dig, run_vision=True)
                if r.get("ok"):
                    _badge_only("photos_enrich", "ok", "Tags updated")
                else:
                    _soft_note("Couldn’t re-tag", "Try again in a moment.")
                st.rerun()
        with b2:
            if st.button("Remove from iPhone", type="primary", use_container_width=True, key="photo_dlg_rm"):
                from cumulous.photo_offload import request_device_delete

                r = request_device_delete(dig, source="mac", execute_afc=True)
                if r.get("ok"):
                    _flash_ok("Removed from phone", "Still safe in your Cumulous backup.")
                else:
                    _soft_note("Couldn’t remove", r.get("message") or "Plug in the iPhone with USB.")
                st.rerun()


def _render_photo_lightbox() -> None:
    """Open centered preview; Streamlit dialog close / × / Done all dismiss."""
    st.session_state["photos_lightbox_open"] = True
    try:
        _photo_lightbox_dialog()
    except Exception:
        # Fallback inline panel if dialog unavailable
        dig = st.session_state.get("photos_selected")
        if not dig:
            return
        from cumulous.photo_library import preview_kind, resolve_media_path, thumb_bytes
        from cumulous.photo_tagging import get_tags

        st.markdown("---")
        c0, c1 = st.columns([1, 10])
        with c0:
            if st.button("×", key="photo_inline_x", help="Close window"):
                _close_photo_viewer()
                st.rerun()
        kind = preview_kind(dig)
        path = resolve_media_path(dig)
        if kind == "video" and path:
            st.video(str(path))
        else:
            data = thumb_bytes(dig)
            if data:
                st.image(data, use_container_width=True)
        # No metadata caption by default (photo only)
        if st.button("Close preview", key="photo_inline_close"):
            _close_photo_viewer()
            st.rerun()


def _render_photo_grid(items: list, *, max_n: int = 48) -> None:
    """Thumbnail/preview grid for photos and videos; click opens lightbox."""
    from cumulous.photo_library import preview_kind, resolve_media_path, thumb_bytes

    items = items[:max_n]
    if not items:
        return
    n_cols = 8
    cols = st.columns(n_cols)
    for i, it in enumerate(items):
        dig = it.get("digest") or ""
        with cols[i % n_cols]:
            kind = it.get("media_type") or preview_kind(dig)
            data = thumb_bytes(dig) if dig else None
            if data:
                st.image(data, use_container_width=True)
            else:
                path = resolve_media_path(dig)
                if path and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                    try:
                        st.image(str(path), use_container_width=True)
                    except Exception:
                        st.caption("▶" if kind == "video" else (it.get("name") or dig[:8]))
                else:
                    st.caption("▶ video" if kind == "video" else (it.get("name") or dig[:8]))
            if kind == "video":
                st.caption("Video")
            label = (it.get("place_name") or it.get("name") or "Open")[:18]
            if st.button(label or "Open", key=f"phsel_{dig[:18]}_{i}", use_container_width=True):
                st.session_state["photos_selected"] = dig
                st.session_state["photos_lightbox_open"] = True
                st.rerun()


def _render_storage_optimize_backup_gate(*, device_id: str) -> None:
    """Mandatory prompt at the start of Backup Now: run intelligent free-space pass?"""
    from cumulous.photo_offload import load_prefs
    from cumulous.storage_optimize import plan_optimization, should_prompt_at_backup

    if not should_prompt_at_backup():
        st.session_state["storage_opt_answered"] = True
        return

    prefs = load_prefs()
    default_mode = str(prefs.get("storage_optimize_mode") or "balanced")
    if default_mode not in ("conservative", "balanced", "aggressive"):
        default_mode = "balanced"

    st.markdown("<div class='cs-header'>Storage optimization</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='cs-card' style='margin-bottom:0.65rem'>"
        "<b>Before this backup</b><br>"
        "<span class='cs-muted'>Cumulous can free space on the iPhone using only photos/videos "
        "already dual-mirrored (Mac + Nextcloud). Favorites, Snapchat, and recent items stay. "
        "Nothing is removed from your Cumulous vault.</span></div>",
        unsafe_allow_html=True,
    )

    mode = st.selectbox(
        "Optimization strength",
        options=["conservative", "balanced", "aggressive"],
        index=["conservative", "balanced", "aggressive"].index(default_mode),
        format_func=lambda m: {
            "conservative": "Conservative — older & large only",
            "balanced": "Balanced (recommended)",
            "aggressive": "Aggressive — more freeable after dual-verify",
        }.get(m, m),
        key="storage_opt_mode_select",
    )
    st.session_state["storage_opt_mode"] = mode

    if st.button("Refresh free-space plan", use_container_width=True, key="storage_opt_plan_btn"):
        plan = plan_optimization(device_id=device_id, mode=mode)  # type: ignore[arg-type]
        st.session_state["storage_opt_plan"] = plan
        st.rerun()

    plan = st.session_state.get("storage_opt_plan")
    if not plan or plan.get("mode") != mode:
        plan = plan_optimization(device_id=device_id, mode=mode)  # type: ignore[arg-type]
        st.session_state["storage_opt_plan"] = plan

    mb = plan.get("projected_mb") or 0
    n = plan.get("selected_count") or 0
    st.markdown(
        f"<div class='cs-card'><span class='cs-status-ok'>●</span> "
        f"<b>Plan:</b> ~{mb} MB freeable · {n} items · "
        f"avg restore confidence {plan.get('avg_confidence') or 0}"
        f"<br><span class='cs-muted'>{html.escape(str(plan.get('message') or ''))}</span></div>",
        unsafe_allow_html=True,
    )

    if st.session_state.get("storage_opt_answered"):
        choice = "Yes — free space first" if st.session_state.get("storage_opt_run_pending") or st.session_state.get("storage_opt_ran") else "No — backup only"
        st.caption(f"Your choice for this backup: {choice}")
        if st.button("Change storage choice", key="storage_opt_reset"):
            st.session_state["storage_opt_answered"] = False
            st.session_state.pop("storage_opt_run_pending", None)
            st.session_state.pop("storage_opt_ran", None)
            st.rerun()
        return

    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "Yes — optimize storage first",
            type="primary",
            use_container_width=True,
            key="storage_opt_yes",
        ):
            st.session_state["storage_opt_answered"] = True
            st.session_state["storage_opt_run_pending"] = n > 0
            st.session_state["storage_opt_ran"] = False
            if n <= 0:
                _soft_note("Nothing to free yet", "Dual-mirror more photos, then try again.")
            else:
                _flash_ok("Will free space first", f"~{mb} MB planned when backup starts.")
            st.rerun()
    with c2:
        if st.button("No — skip, just backup", use_container_width=True, key="storage_opt_no"):
            st.session_state["storage_opt_answered"] = True
            st.session_state["storage_opt_run_pending"] = False
            st.session_state["storage_opt_ran"] = False
            _badge_only("storage_opt", "ok", "Skipped for this backup")
            st.rerun()


def _device_delete_line(
    *,
    category_id: str,
    subcategory_id: str = "",
    device_id: str = "",
) -> dict:
    """Clear only this line’s freeable data from the phone (vault kept)."""
    from cumulous.backup_categories import free_category_from_device, free_subcategory_from_device

    if subcategory_id:
        return free_subcategory_from_device(
            category_id,
            subcategory_id,
            device_id=device_id,
            source="mac",
        )
    return free_category_from_device(category_id, device_id=device_id, source="mac")


def _line_action_row(
    *,
    surface: str,
    line_id: str,
    title: str,
    device_id: str,
    apple_id: str,
    category_id: str,
    subcategory_id: str = "",
) -> None:
    """Compact Backup | Restore | Device Delete — same total row width as before."""
    from cumulous.selective_backup import backup_selected, restore_selected

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button(
            "Backup",
            key=f"line_bak_{surface}_{line_id}",
            type="primary",
            use_container_width=True,
            help=f"Back up only {title}",
        ):
            res = backup_selected(
                [line_id if "." in line_id or line_id.startswith("app.") else category_id],
                device_id=device_id,
                apple_account_id=apple_id,
                background=True,
            )
            if res.get("ok"):
                _flash_ok("Backup started", res.get("message") or title)
            else:
                _soft_note("Backup", res.get("message") or res.get("error") or "Failed")
            st.rerun()
    with b2:
        if st.button(
            "Restore",
            key=f"line_rst_{surface}_{line_id}",
            type="primary",
            use_container_width=True,
            help=f"Restore only {title} from vault",
        ):
            res = restore_selected(
                [line_id if "." in line_id or line_id.startswith("app.") else category_id],
                device_id=device_id,
            )
            if res.get("ok"):
                _flash_ok("Restore staged", res.get("message") or res.get("dest") or "")
            else:
                _soft_note("Restore", res.get("message") or "Nothing to restore.")
            st.rerun()
    with b3:
        if st.button(
            "Device Delete",
            key=f"line_del_{surface}_{line_id}",
            type="primary",
            use_container_width=True,
            help=f"Clear {title} from the phone only (vault kept)",
        ):
            res = _device_delete_line(
                category_id=category_id,
                subcategory_id=subcategory_id,
                device_id=device_id,
            )
            if res.get("ok"):
                _flash_ok("Device Delete", res.get("message") or "Removed from phone · vault kept.")
            else:
                _soft_note(
                    "Device Delete",
                    res.get("message") or res.get("error") or "USB required or not freeable.",
                )
            st.rerun()


def _render_backup_completion_list(*, surface: str = "home") -> None:
    """List verified backup categories with sizes and Backup | Restore | Device Delete."""
    from cumulous.backup_categories import evaluate_categories

    try:
        from cumulous.devices import probe_connected_device

        _probe = probe_connected_device() or {}
        _did = str(
            _probe.get("imei")
            or _probe.get("device_id")
            or st.session_state.get("primary_device_id")
            or "354345290021725"
        )
        report = evaluate_categories(device_id=_did, use_ai=False)
    except Exception:
        return
    summ = report.get("summary") or {}
    total_label = summ.get("total_backed_up_label") or "—"
    st.markdown(
        f"<div class='cs-header'>Backed up · {html.escape(str(report.get('device_name') or 'Device'))}</div>"
        f"<div class='cs-muted' style='margin-bottom:0.55rem'>"
        f"{summ.get('categories_verified', 0)}/{summ.get('categories_total', 0)} categories verified · "
        f"{summ.get('subcategories_verified', 0)}/{summ.get('subcategories_total', 0)} data types · "
        f"{summ.get('photos_dual', 0)} photos dual-mirrored · "
        f"<b style='color:#fff'>{html.escape(str(total_label))}</b> in vault"
        f"</div>",
        unsafe_allow_html=True,
    )
    device_id = str(report.get("device_id") or "")
    apple_id = _primary_apple_id() or ""

    for cat in report.get("categories") or []:
        ok = bool(cat.get("verified"))
        check = (
            "<span style='color:#007AFF;font-weight:700'>✓</span>"
            if ok
            else "<span style='color:#636366'>·</span>"
        )
        size_label = html.escape(str(cat.get("size_label") or "—"))
        st.markdown(
            f"<div class='cs-card' style='padding:0.85rem 1rem'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;gap:8px'>"
            f"<div style='font-weight:600;letter-spacing:-0.02em'>{check} "
            f"{html.escape(str(cat.get('title') or cat.get('id')))}"
            f" <span class='cs-muted' style='font-weight:500;font-size:0.86rem'>"
            f"· {size_label}</span></div>"
            f"<span class='cs-muted' style='font-size:0.75rem'>"
            f"{cat.get('sub_verified', 0)}/{cat.get('sub_total', 0)} verified</span></div>",
            unsafe_allow_html=True,
        )
        _line_action_row(
            surface=surface,
            line_id=str(cat["id"]),
            title=str(cat.get("title") or cat["id"]),
            device_id=device_id,
            apple_id=apple_id,
            category_id=str(cat["id"]),
        )

        for sub in cat.get("subcategories") or []:
            s_ok = bool(sub.get("verified"))
            s_chk = (
                "<span style='color:#007AFF'>✓</span>"
                if s_ok
                else "<span style='color:#636366'>·</span>"
            )
            sub_size = html.escape(str(sub.get("size_label") or "—"))
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;gap:8px;"
                f"padding:0.28rem 0 0.1rem 0.35rem;font-size:0.86rem'>"
                f"<span>{s_chk} {html.escape(str(sub.get('title') or ''))}"
                f" <span class='cs-muted'>· {sub_size}</span></span>"
                f"<span class='cs-muted' style='font-size:0.75rem'>"
                f"{html.escape(str(sub.get('detail') or ''))}</span></div>",
                unsafe_allow_html=True,
            )
            line_id = f"{cat['id']}.{sub['id']}"
            _line_action_row(
                surface=surface,
                line_id=line_id,
                title=str(sub.get("title") or sub["id"]),
                device_id=device_id,
                apple_id=apple_id,
                category_id=str(cat["id"]),
                subcategory_id=str(sub["id"]),
            )
        st.markdown("</div>", unsafe_allow_html=True)


def _render_confirm_user_panel() -> None:
    """Centered confirm flow: instructions → 4-digit → 2FA → unlock restore.

    When auth_policy skips 2FA, auto-unlock without codes.
    """
    flow = st.session_state.get("confirm_flow")
    if not flow:
        return

    from cumulous.auth_policy import auth_required_for_backup, verification_paused_message

    if not auth_required_for_backup():
        flow["step"] = "done"
        flow["unlocked"] = True
        st.session_state["confirm_flow"] = flow
        st.session_state["confirm_user_unlocked"] = True
        st.caption(verification_paused_message())
        st.markdown("<div class='cs-header'>Access unlocked</div>", unsafe_allow_html=True)
        st.success("Verification paused for this build — restore tools available.")
        return

    st.markdown("<div class='cs-header'>Confirm 4-Digit Code</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 3, 1])
    with c2:
        st.markdown(
            f"<div class='cs-card'>"
            f"<b>{flow.get('device_name') or flow.get('device_id')}</b><br>"
            f"<span class='cs-muted'>Apple Account · {flow.get('apple_id') or '—'}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if _esc_button("confirm_esc"):
            _dismiss_confirm_dialog(cancel_flow=True)
            st.rerun()

        step = flow.get("step") or "code"

        if step == "code":
            st.markdown(
                "<div class='confirm-instructions'>"
                "<b>1.</b> A 4-digit code is pushed live to your iPhone and other Apple devices.<br>"
                "<b>2.</b> Enter that code in the dialog box (or the field below).<br>"
                "<b>3.</b> Then enter your 6-digit 2FA for this Apple Account."
                "</div>",
                unsafe_allow_html=True,
            )
            if not st.session_state.get("confirm_code_shown"):
                # Hard-cap: spawn once; reuse if already active
                ch = spawn_challenge_for_apple_account(
                    purpose="confirm_user",
                    apple_account_id=flow["apple_id"],
                    include_mac_mini=True,
                    force_new=False,
                )
                flow["challenge_id"] = ch.get("challenge_id")
                flow["fanout"] = ch.get("fanout_device_ids") or []
                flow["fanout_labels"] = ch.get("fanout_device_labels") or flow["fanout"]
                flow["push_results"] = ch.get("push_results") or []
                st.session_state["confirm_flow"] = flow
                st.session_state["confirm_code_shown"] = True
                labels = flow["fanout_labels"]
                summary = ", ".join(str(x) for x in labels[:8]) if labels else "linked devices"
                _flash_code(
                    ch["code"],
                    title="Confirm 4-Digit Code",
                    instructions=(
                        "One code only — pushed to ROB IPHONE (USB/Wi‑Fi), other linked "
                        "Apple devices, and this Mac. Map shows request location."
                    ),
                    fanout_summary=summary,
                )
                st.rerun()

            # Exactly one dialog phase at a time — never re-open after dismiss
            if st.session_state.get("confirm_delivery_open"):
                _confirm_delivery_dialog()
            elif st.session_state.get("confirm_input_open"):
                _confirm_input_dialog()

            st.markdown("##### Or enter code here")
            code_in = st.text_input(
                "4-digit code",
                max_chars=4,
                key="confirm_4digit",
                placeholder="••••",
            )
            b1, b2 = st.columns(2)
            with b1:
                if st.button("Verify code", type="primary", use_container_width=True, key="btn_verify_4"):
                    set_status("confirm_user", "running", message="Checking 4-digit code…")
                    if verify_challenge(code_in, purpose="confirm_user"):
                        flow["step"] = "totp"
                        st.session_state["confirm_flow"] = flow
                        st.session_state["confirm_dialog_open"] = False
                        st.session_state["confirm_delivery_open"] = False
                        st.session_state["confirm_input_open"] = False
                        clear_flashes(st)
                        set_status("confirm_user", "ok", message="4-digit verified")
                        _flash_ok("Code Accepted", "Enter 2FA next.")
                        st.rerun()
                    else:
                        set_status("confirm_user", "error", message="Invalid or expired code")
                        _soft_note("Needs a moment", "Wrong or expired code. Use New code only if needed.")
            with b2:
                if st.button("New code", use_container_width=True, key="btn_resend_4"):
                    # Explicit force_new after user action — still replaces prior (one only)
                    st.session_state["confirm_code_shown"] = False
                    st.session_state["confirm_delivery_open"] = False
                    st.session_state["confirm_input_open"] = False
                    ch = spawn_challenge_for_apple_account(
                        purpose="confirm_user",
                        apple_account_id=flow["apple_id"],
                        include_mac_mini=True,
                        force_new=True,
                    )
                    flow["challenge_id"] = ch.get("challenge_id")
                    flow["fanout"] = ch.get("fanout_device_ids") or []
                    flow["fanout_labels"] = ch.get("fanout_device_labels") or flow["fanout"]
                    st.session_state["confirm_flow"] = flow
                    st.session_state["confirm_code_shown"] = True
                    _flash_code(
                        ch["code"],
                        title="Confirm 4-Digit Code",
                        fanout_summary=", ".join(str(x) for x in (flow["fanout_labels"] or [])[:8]),
                    )
                    st.rerun()
            render_action_badge(st, "confirm_user")
            labels = flow.get("fanout_labels") or flow.get("fanout") or []
            if labels:
                st.caption("Devices notified: " + ", ".join(str(x) for x in labels[:12]))
            pushes = flow.get("push_results") or []
            if pushes:
                ok_n = sum(1 for p in pushes if "deliver" in str(p.get("status") or ""))
                st.caption(f"Live push: {ok_n}/{len(pushes)} channel(s) delivered")

        elif step == "totp":
            clear_flashes(st)
            st.markdown(
                "<div class='confirm-instructions'>"
                "Enter the <b>6-digit 2FA</b> for this Apple Account "
                "(one authenticator secret per Apple Account — also stored for CEO in local <code>2xsecrets</code>)."
                "</div>",
                unsafe_allow_html=True,
            )
            # Ensure secret exists
            ensure_account_2fa(flow["apple_id"])
            totp = st.text_input("6-digit 2FA", max_chars=6, key="confirm_totp")
            if st.button("Verify 2FA & unlock", type="primary", use_container_width=True):
                set_status("confirm_user", "running", message="Checking 2FA…")
                if verify_account_2fa(flow["apple_id"], totp):
                    flow["step"] = "unlocked"
                    st.session_state["confirm_flow"] = flow
                    st.session_state["restore_unlocked"] = {
                        "device_id": flow["device_id"],
                        "apple_id": flow["apple_id"],
                        "gen_id": flow.get("gen_id"),
                        "until": time.time() + 3600,
                    }
                    set_status("confirm_user", "ok", message="Identity confirmed")
                    _flash_ok("Unlocked", "You can view or restore this backup.")
                    st.rerun()
                else:
                    set_status("confirm_user", "error", message="2FA rejected")
                    _soft_note("Needs a moment", "2FA code not accepted.")
            render_action_badge(st, "confirm_user")

        elif step == "unlocked":
            st.markdown(
                "<div class='cs-card'><span class='cs-status-ok'>●</span> "
                "<b>Identity confirmed</b> — view or restore on this Mac Mini.</div>",
                unsafe_allow_html=True,
            )
            gen = flow.get("gen_id")
            if not gen:
                _soft_note("Heads up", "No backup generation selected.")
            else:
                if st.button("View / restore on this Mac Mini", type="primary", use_container_width=True):
                    res = restore_to_mac(flow["device_id"], gen, action_id="restore_device")
                    if res.get("ok"):
                        _flash_ok("Restored", f"{res.get('file_count')} files on this Mac")
                    else:
                        _soft_note("Needs a moment", res.get("error") or "Restore failed")
                    st.rerun()
                render_action_badge(st, "restore_device")
                st.caption(f"Files open in Finder under: {restore_export_root()}")


def _render_backup_catalog() -> None:
    catalog = catalog_by_apple_account()
    if not catalog:
        st.markdown(
            "<div class='cs-card cs-muted'>No Apple Accounts yet. "
            "Press <b>Sync Apple Account</b> to scrape the Apple ID signed into this Mac.</div>",
            unsafe_allow_html=True,
        )
        return

    for acct in catalog:
        verified = "Verified" if acct.get("verified") else "Unverified"
        vcolor = "#30d158" if acct.get("verified") else "#ffd60a"
        ceo = " · CEO" if acct.get("is_ceo") else ""
        st.markdown(
            f"<div class='cs-acct'>"
            f"<div class='cs-header'>Apple Account{ceo}</div>"
            f"<div style='font-size:1.15rem;font-weight:600'>{acct.get('display_name') or acct.get('apple_id')}</div>"
            f"<div class='cs-muted'>{acct.get('apple_id')} · "
            f"<span style='color:{vcolor}'>{verified}</span> · {acct.get('source') or 'local'}</div>",
            unsafe_allow_html=True,
        )
        devices = acct.get("devices") or []
        if not devices:
            st.caption("No devices under this account yet.")
        for d in devices:
            backed = d.get("backed_up")
            badge = (
                "<span class='cs-badge' style='background:#30d15822;color:#30d158;border:1px solid #30d15855'>Backed up</span>"
                if backed
                else "<span class='cs-badge' style='background:#007AFF22;color:#007AFF;border:1px solid #007AFF55'>Not backed up</span>"
            )
            st.markdown(
                f"<div class='cs-dev'><h4>{d.get('display_name')} {badge}</h4>"
                f"<div class='cs-muted'>{d.get('model') or 'Apple device'} · "
                f"Head: {d.get('head') or '—'}</div></div>",
                unsafe_allow_html=True,
            )
            gens = d.get("generations") or []
            if gens:
                for g in gens[:5]:
                    cols = st.columns([3, 2, 2])
                    with cols[0]:
                        st.caption(
                            f"{'Latest · ' if g.get('is_head') else ''}"
                            f"{_fmt_ts(g.get('created_at'))}"
                        )
                    with cols[1]:
                        st.caption(f"{g.get('file_count') or 0} items")
                    with cols[2]:
                        if st.button(
                            "Confirm User",
                            key=f"cu_{d['device_id']}_{g.get('gen_id')}",
                            use_container_width=True,
                        ):
                            st.session_state["confirm_flow"] = {
                                "device_id": d["device_id"],
                                "device_name": d.get("display_name"),
                                "apple_id": acct.get("apple_id"),
                                "gen_id": g.get("gen_id"),
                                "step": "code",
                            }
                            st.session_state.pop("confirm_code_shown", None)
                            clear_flashes(st)
                            st.rerun()
            else:
                st.caption("No backups yet — use Backup Now while the phone is connected.")
        st.markdown("</div>", unsafe_allow_html=True)


def _unified_backup_progress_view() -> dict:
    """Merge full-system + photo harvest + music harvest into one accurate progress payload."""
    from cumulous.backup_session import session_public_view

    view = dict(session_public_view() or {})
    # Photo harvest percent (items dual-mirrored vs device inventory)
    try:
        from cumulous.photo_offload import harvest_progress

        hp = harvest_progress() or {}
        if hp.get("active") or (hp.get("harvest") or {}).get("status") == "running":
            harv = hp.get("harvest") or {}
            inv = hp.get("device_inventory") or {}
            mirrored = float(harv.get("mirrored") or 0) + float(harv.get("skipped_existing") or 0)
            total = float(
                inv.get("media_total")
                or harv.get("total_estimate")
                or max(mirrored + float(harv.get("pending") or 0), mirrored, 1)
            )
            photo_pct = min(99.9, max(0.0, 100.0 * mirrored / max(total, 1.0)))
            if harv.get("status") == "complete":
                photo_pct = 100.0
            # Prefer fuller system % when active; else show photo harvest
            if not view.get("active") or float(view.get("percent") or 0) < 1:
                view.update(
                    {
                        "active": True,
                        "status": "running",
                        "percent": photo_pct,
                        "percent_int": int(round(photo_pct)),
                        "status_line": hp.get("status_line") or "Photo backup",
                        "kind": "photos",
                        "bytes_done_label": f"{int(mirrored)} items",
                        "bytes_total_label": f"{int(total)} on device",
                        "unplug_safe": True,
                    }
                )
            else:
                view["status_line"] = (
                    f"{view.get('status_line') or 'Backup'} · photos {int(photo_pct)}%"
                )
                view["photo_percent"] = photo_pct
    except Exception:
        pass
    # Music harvest
    try:
        from cumulous.music_offload import music_harvest_progress

        mp = music_harvest_progress() or {}
        mh = mp.get("harvest") or {}
        if mh.get("status") == "running" or mp.get("alive"):
            mirrored_m = float(mh.get("mirrored") or 0) + float(mh.get("skipped_existing") or 0)
            total_m = float(mh.get("total_estimate") or mh.get("scanned") or max(mirrored_m, 1))
            music_pct = min(99.9, max(0.0, 100.0 * mirrored_m / max(total_m, 1.0)))
            if not view.get("active"):
                view.update(
                    {
                        "active": True,
                        "status": "running",
                        "percent": music_pct,
                        "percent_int": int(round(music_pct)),
                        "status_line": f"Music backup · {int(mirrored_m)} items",
                        "kind": "music",
                        "unplug_safe": True,
                    }
                )
    except Exception:
        pass
    # Clamp + floor so % never jumps backwards *during live transfer only*.
    # Do not pin a poison 99% Streamlit floor when backend recalibrates downward.
    pct = float(view.get("percent") or 0)
    floor = float(st.session_state.get("_bak_pct_floor") or 0)
    live_run = bool(view.get("process_alive")) and str(view.get("status") or "") in (
        "running",
        "waiting_passcode",
    )
    src = str(view.get("percent_source") or "")
    if view.get("status") == "complete":
        pct = 100.0
        st.session_state.pop("_bak_pct_floor", None)
    elif live_run and src in (
        "console_live",
        "console_bytes",
        "evidence_recalibrate",
        "disk_or_floor_while_tiny_live",
        "hold_prior_wait",
        "max_evidence_and_high_water",
        "session_high_only",
    ):
        # Trust backend multi-signal % — drop poison floor if backend went lower
        if floor >= 99.0 and pct < 95.0:
            floor = pct
        if pct + 0.5 < floor and pct >= 1.0:
            st.session_state["_bak_pct_floor"] = pct
            floor = pct
        else:
            pct = max(pct, floor) if floor < 99.0 else pct
            st.session_state["_bak_pct_floor"] = pct
    elif view.get("active") and view.get("paused"):
        # Paused: show held high-water, do not invent growth; clear poison 99 floor
        if floor >= 99.0 and pct < 95.0:
            floor = pct
        pct = max(pct, floor) if floor > 0 else pct
        st.session_state["_bak_pct_floor"] = pct
    elif view.get("active"):
        if floor >= 99.0 and pct < 95.0:
            floor = pct
        pct = max(pct, floor) if floor < 99.0 else pct
        st.session_state["_bak_pct_floor"] = pct
    else:
        st.session_state.pop("_bak_pct_floor", None)
    view["percent"] = pct
    if view.get("status") == "complete":
        view["percent_int"] = 100
    else:
        view["percent_int"] = max(0, min(98, int(pct)))
    return view


def _render_backup_progress_window() -> None:
    """Mac mini-window: live accurate % bar, traffic-light close/minimize, click-outside to hide."""
    from datetime import timedelta

    view = _unified_backup_progress_view()
    if not view.get("active") and view.get("status") != "complete":
        return

    # Live fragment re-polls every 2s so % stays accurate without manual refresh
    @st.fragment(run_every=timedelta(seconds=2) if view.get("active") else None)
    def _progress_body() -> None:
        v = _unified_backup_progress_view()
        if not v.get("active") and v.get("status") != "complete":
            return

        if st.session_state.get("hide_backup_window") and v.get("status") != "complete":
            if st.button("Show backup progress", key="show_bak_win", type="primary", use_container_width=True):
                st.session_state["hide_backup_window"] = False
                st.rerun()
            return

        pct = float(v.get("percent") or 0)
        pct_i = int(v.get("percent_int") or round(pct))
        pct_i = max(0, min(100, pct_i))
        width = min(100.0, max(0.0, pct))
        status_line = html.escape(str(v.get("status_line") or "Backing up"))
        device = html.escape(str(v.get("device_name") or v.get("label") or "Device"))
        transport = html.escape(str((v.get("transport") or "")).upper() or "—")
        done_l = html.escape(str(v.get("bytes_done_label") or ""))
        tot_l = html.escape(str(v.get("bytes_total_label") or ""))
        data_line = ""
        if done_l or tot_l:
            data_line = f"{done_l}" + (f" of {tot_l}" if tot_l else "")
        elif v.get("disk_bytes"):
            mb = float(v.get("disk_bytes") or 0) / (1024 * 1024)
            data_line = f"{mb:,.1f} MB copied to vault"
        waiting = bool(v.get("waiting_passcode"))
        paused = bool(v.get("paused")) or (
            not v.get("process_alive") and str(v.get("status") or "") in (
                "needs_resume", "awaiting_usb", "awaiting_network",
            )
        )
        tip = ""
        if waiting:
            tip = (
                "<div class='cs-muted' style='margin-top:0.65rem;padding:0.7rem 0.8rem;"
                "background:rgba(255,255,255,0.04);border:1px solid var(--cs-line);"
                "border-radius:14px;font-size:0.82rem;line-height:1.45'>"
                "<b style='color:#fafafa'>On the iPhone once:</b> enter your passcode if Apple asks "
                "(even if already unlocked). Progress holds. Leave Cumulous open."
                "</div>"
            )
        elif paused:
            tip = (
                "<div class='cs-muted' style='margin-top:0.65rem;padding:0.7rem 0.8rem;"
                "background:rgba(255,214,10,0.08);border:1px solid rgba(255,214,10,0.28);"
                "border-radius:14px;font-size:0.82rem;line-height:1.45'>"
                "<b style='color:#ffd60a'>Paused</b> — percent held from last progress. "
                "Plug USB and unlock the iPhone. Backup will resume automatically."
                "</div>"
            )
        elif v.get("unplug_safe") and v.get("active") and v.get("process_alive"):
            tip = (
                "<div style='margin-top:0.5rem;font-size:0.75rem;color:#8e8e93;line-height:1.4'>"
                "Unplug anytime — backup continues over Wi‑Fi when available."
                "</div>"
            )

        # Click outside (backdrop) → minimize without cancelling backup
        st.markdown(
            '<div class="cs-backdrop-hit" title="Click outside to minimize">',
            unsafe_allow_html=True,
        )
        if st.button(" ", key="bak_click_outside", help="Click outside window to minimize", use_container_width=True):
            st.session_state["hide_backup_window"] = True
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        # Traffic lights + sheet
        t1, t2, t3, tspace = st.columns([0.07, 0.07, 0.07, 0.79])
        with t1:
            if st.button("×", key="bak_close_tl", help="Close progress", type="secondary"):
                st.session_state["hide_backup_window"] = True
                st.rerun()
        with t2:
            if st.button("–", key="bak_min_tl", help="Minimize progress", type="secondary"):
                st.session_state["hide_backup_window"] = True
                st.rerun()
        with t3:
            st.markdown(
                "<div style='width:14px;height:14px;border-radius:50%;background:#28c840;"
                "border:0.5px solid #1aab29;margin-top:10px;opacity:0.85'></div>",
                unsafe_allow_html=True,
            )

        bar = (
            f"<div class='cs-progress-track'>"
            f"<div class='cs-progress-fill' style='width:{width:.2f}%'></div></div>"
        )
        st.markdown(
            f"""
<div class="cs-progress-sheet cs-dismissable-sheet" id="cumulous-backup-progress-sheet" style="margin:0 auto">
  <div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px">
    <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.12em;color:#8e8e93">
      Backup progress
    </div>
    <div class="cs-progress-pct">{pct_i}%</div>
  </div>
  <div style="padding:0.75rem 0 0.35rem">{bar}</div>
  <div style="font-size:0.88rem;color:#e8e8ed;margin-top:0.4rem;line-height:1.45">
    {status_line}
  </div>
  <div style="font-size:0.78rem;color:#a1a1a6;margin-top:0.25rem;line-height:1.4">
    {html.escape(data_line) if data_line else f"{device} · {transport}"}
  </div>
  {tip}
  <div style="font-size:0.68rem;color:#636366;margin-top:0.65rem">
    Red closes · yellow minimizes · click outside to hide · backup keeps running
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        if v.get("status") == "complete":
            if st.button("Dismiss", key="bak_dismiss", type="primary", use_container_width=True):
                st.session_state["hide_backup_window"] = True
                st.session_state.pop("_bak_pct_floor", None)
                st.rerun()

    _progress_body()


def main() -> None:
    _bootstrap()
    if not st.session_state.get("splash_done"):
        render_splash(st)
        return

    # One-time migrate: Apple Account model
    if not st.session_state.get("migrated_apple"):
        try:
            migrate_devices_to_primary_apple_account()
        except Exception:
            sync_scraped_accounts()
        st.session_state["migrated_apple"] = True

    render_flashes(st)
    _render_backup_progress_window()

    st.markdown(
        f"<div class='cs-hero'>"
        f"<div class='cs-hero-title'>{PRODUCT_NAME}</div>"
        f"<div class='cs-hero-sub'>Private backup · by device · v{__version__}</div></div>",
        unsafe_allow_html=True,
    )

    # Custom tab bar — 2 rows so full labels fit on one line (no mid-word wrap)
    TAB_DEFS = [
        ("home", "Home"),
        ("photos", "Photos"),
        ("backups", "Backups"),
        ("devices", "Devices"),
        ("backup_now", "Backup Now"),
        ("install", "Install on Phones"),
        ("settings", "Settings"),
        ("ceo", "CEO Override"),
    ]
    st.markdown(
        """
<style>
/* Tab labels: single line, never break mid-word */
div[data-testid="stHorizontalBlock"] button[kind="primary"],
div[data-testid="stHorizontalBlock"] button[kind="secondary"] {
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  min-height: 40px !important;
  font-size: 0.88rem !important;
  padding: 0.45rem 0.5rem !important;
  line-height: 1.2 !important;
}
</style>
""",
        unsafe_allow_html=True,
    )
    try:
        qp_tab = st.query_params.get("tab")
        if isinstance(qp_tab, list):
            qp_tab = qp_tab[0] if qp_tab else None
        if qp_tab and any(qp_tab == k for k, _ in TAB_DEFS):
            st.session_state["cumulous_tab"] = qp_tab
    except Exception:
        pass
    if "cumulous_tab" not in st.session_state:
        st.session_state["cumulous_tab"] = "home"
    # Two rows of four — each tab wide enough for full phrase
    for row in (TAB_DEFS[:4], TAB_DEFS[4:]):
        nav = st.columns(len(row))
        for i, (tkey, tlabel) in enumerate(row):
            with nav[i]:
                active = st.session_state["cumulous_tab"] == tkey
                if st.button(
                    tlabel,
                    key=f"cumulous_nav_{tkey}",
                    type="primary" if active else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["cumulous_tab"] = tkey
                    try:
                        st.query_params["tab"] = tkey
                    except Exception:
                        pass
                    st.rerun()
    tab = st.session_state.get("cumulous_tab") or "home"

    inv = device_inventory(user_says_plugged=bool(st.session_state.get("user_says_plugged")))
    primary = _primary_apple_id()

    # —— Home ——
    if tab == "home":
        st.markdown("<div class='cs-header'>Status</div>", unsafe_allow_html=True)
        # Status tiles: label with colon + traffic-light value glow (deepcheck-aligned HIG)
        _st_storage_ok = bool(externalssd_mounted())
        _st_vault_ok = bool(vault_root())
        _st_apple_ok = bool(primary)
        _st_ceo_ok = bool(bearaccount_exists())
        def _status_tile(label: str, value: str, affirmed: bool) -> str:
            cls = "ok" if affirmed else "bad"
            return (
                f"<div class='cs-status-tile {cls}'>"
                f"<span class='cs-status-label'>{label}</span>"
                f"<span class='cs-status-value'>{value}</span>"
                f"</div>"
            )
        st.markdown(
            "<div class='cs-status-row'>"
            + _status_tile("Storage:", "Online" if _st_storage_ok else "Offline", _st_storage_ok)
            + _status_tile("Vault:", "Ready" if _st_vault_ok else "—", _st_vault_ok)
            + _status_tile("Apple ID:", "Linked" if _st_apple_ok else "None", _st_apple_ok)
            + _status_tile("CEO gate:", "Ready" if _st_ceo_ok else "Setup", _st_ceo_ok)
            + "</div>",
            unsafe_allow_html=True,
        )

        # Phone line — Live (green pulse) / No Connection (red pulse)
        line = inv.get("status_line") or "No iPhone connected"
        ok = inv.get("usbmux_seen")
        live_cls = "live-pulse" if ok else "dead-pulse"
        live_label = "Live" if ok else "No Connection"
        st.markdown(
            f"<div class='cs-card' style='display:flex;align-items:center;justify-content:space-between;gap:12px'>"
            f"<div><span class='{'cs-status-ok' if ok else 'cs-status-err'}'>●</span> "
            f"<b style='letter-spacing:-0.02em'>{line}</b>"
            f"<div class='cs-muted' style='margin-top:0.35rem'>Unplug-safe backup · continues on Wi‑Fi</div></div>"
            f"<span class='cs-chip {live_cls}'>{live_label}</span></div>",
            unsafe_allow_html=True,
        )
        if primary:
            st.caption(f"Apple Account linked on this Mac")

        # Capacity honesty — not “255 GB zipped into 9 GB”
        try:
            from cumulous.device_capacity import capacity_report_html

            st.markdown(capacity_report_html(), unsafe_allow_html=True)
        except Exception:
            pass

        # Verified categories — Home only (not repeated on other tabs)
        _render_backup_completion_list(surface="home")

        st.markdown("<div class='cs-header'>Actions</div>", unsafe_allow_html=True)
        a1, a2, a3 = st.columns(3)
        with a1:
            if st.button("Sync Apple Account", use_container_width=True, key="home_sync"):
                set_status("sync_apple", "running", message="Linking…")
                res = migrate_devices_to_primary_apple_account()
                if res.get("ok"):
                    _badge_only("sync_apple", "ok", "Apple Account linked")
                    _flash_ok("Account linked")
                else:
                    _badge_only("sync_apple", "error", "Couldn’t link")
                    _soft_note("Couldn’t link", "Sign into iCloud in System Settings, then try again.")
                st.rerun()
            render_action_badge(st, "sync_apple")
        with a2:
            if st.button("Scan for iPhone", use_container_width=True, key="home_scan"):
                set_status("scan_iphone", "running", message="Scanning…")
                st.session_state["user_says_plugged"] = True
                inv2 = device_inventory(user_says_plugged=True)
                if inv2.get("usbmux_seen"):
                    p = inv2.get("primary_probe") or {}
                    name = p.get("display_name") or "iPhone"
                    _badge_only("scan_iphone", "ok", f"Found {name}")
                    _flash_ok("iPhone found", name)
                elif inv2.get("trust_needed"):
                    _badge_only("scan_iphone", "error", "Trust needed")
                    _soft_note("Trust needed", "Unlock the phone and tap Trust.")
                else:
                    _badge_only("scan_iphone", "error", "No iPhone")
                    _soft_note("No iPhone", "Connect with a USB cable and unlock.")
                st.rerun()
            render_action_badge(st, "scan_iphone")
        with a3:
            if st.button("Try Trust / Pair", use_container_width=True, key="home_pair"):
                set_status("pair_iphone", "running", message="Pairing…")
                fresh = probe_connected_device() or (inv.get("primary_probe") or {})
                udid = fresh.get("udid")
                res = attempt_pair(udid)
                if res.get("ok"):
                    _badge_only("pair_iphone", "ok", "Paired")
                    _flash_ok("Paired")
                else:
                    _badge_only("pair_iphone", "error", "Pairing failed")
                    _soft_note("Pairing failed", "Unlock, tap Trust, use a data cable.")
                st.rerun()
            render_action_badge(st, "pair_iphone")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Install phone tools", use_container_width=True, key="home_tools"):
                set_status("install_tools", "running", message="Installing…")
                res = ensure_libimobiledevice()
                if res.get("ok"):
                    _badge_only("install_tools", "ok", "Tools ready")
                    _flash_ok("Tools ready")
                else:
                    _badge_only("install_tools", "error", "Install needed")
                    _soft_note("Tools needed", "Homebrew install of phone tools failed — retry.")
                st.rerun()
            render_action_badge(st, "install_tools")
        with b2:
            if st.button("System check", use_container_width=True, key="home_sys"):
                raw = status_report()
                ok_all = bool(raw.get("idevice_id") and raw.get("idevicebackup2"))
                _badge_only(
                    "system_check",
                    "ok" if ok_all else "error",
                    "All tools ready" if ok_all else "Some tools missing",
                )
                st.rerun()
            render_action_badge(st, "system_check")

        # Confirm panel is mounted once below tabs (avoids duplicate Streamlit keys)

    # —— Photos (Photos.app-like; deeper tags) ——
    if tab == "photos":
        _render_photos_tab()

    # —— Backups (by Apple ID → device) ——
    if tab == "backups":
        st.markdown("<div class='cs-header'>Backups by Apple Account</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='cs-muted' style='margin-bottom:0.75rem'>"
            "No individual login accounts. Devices are listed under their Apple Account. "
            "To view or restore, press <b>Confirm User</b>."
            "</div>",
            unsafe_allow_html=True,
        )
        _render_backup_catalog()

    # —— Devices ——
    if tab == "devices":
        st.markdown("<div class='cs-header'>Devices</div>", unsafe_allow_html=True)
        st.caption("Connected · Paired on this Mac · Registered under Apple Account")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Connected**")
            for d in inv.get("connected") or []:
                st.write(f"• {d.get('display_name')}")
            if not inv.get("connected"):
                st.caption("None")
        with c2:
            st.markdown("**Paired on Mac**")
            for p in (inv.get("paired_on_mac") or [])[:8]:
                st.write(f"• {(p.get('device_id') or '')[:14]}…")
            if not inv.get("paired_on_mac"):
                st.caption("None")
        with c3:
            st.markdown("**Registered**")
            for r in inv.get("registered") or []:
                st.write(f"• {r.get('display_name')}")
            if not inv.get("registered"):
                st.caption("None")

        probe = inv.get("primary_probe") or probe_connected_device()
        if probe:
            st.markdown("<div class='cs-header'>Register connected phone</div>", unsafe_allow_html=True)
            if st.button("Register under my Apple Account", type="primary", use_container_width=True):
                set_status("register_device", "running", message="Registering…")
                aid = primary or _primary_apple_id()
                if not aid:
                    set_status("register_device", "error", message="Sync Apple Account first")
                    _soft_note("Needs a moment", "Sync Apple Account first.")
                else:
                    rid = probe.get("imei") or probe.get("udid")
                    register_device(
                        rid,
                        display_name=probe.get("display_name") or "Apple Device",
                        owner_username=aid,
                        model=probe.get("model") or "",
                        is_ceo_override=True,
                        udid=probe.get("udid") or "",
                        imei=probe.get("imei") or "",
                        apple_account_id=aid,
                    )
                    from cumulous.apple_accounts import attach_device_to_account, ensure_account_2fa

                    attach_device_to_account(aid, rid)
                    totp_info = ensure_account_2fa(aid)
                    set_status("register_device", "ok", message="Device registered", detail=probe.get("display_name") or "")
                    _flash_ok("Device Registered", probe.get("display_name") or "")
                    if totp_info.get("created"):
                        st.session_state["show_new_2fa"] = totp_info.get("totp_secret")
                st.rerun()
            render_action_badge(st, "register_device")
            if st.session_state.get("show_new_2fa"):
                st.markdown(
                    "<div class='cs-card'><b>New 2FA secret</b><br>"
                    "<span class='cs-muted'>Scan once. Also saved for CEO in local 2xsecrets.</span></div>",
                    unsafe_allow_html=True,
                )
                st.code(st.session_state["show_new_2fa"])

    # —— Backup Now ——
    if tab == "backup_now":
        st.markdown("<div class='cs-header'>Backup Now</div>", unsafe_allow_html=True)
        # Selective backup/restore: Apple blue (additive) — global primary theme already applies
        st.markdown(
            """
<style>
.bak-btn-row { display:flex; gap:10px; margin:0.35rem 0 0.5rem 0; }
</style>
""",
            unsafe_allow_html=True,
        )
        from cumulous.selective_backup import (
            backup_all_device_data,
            backup_selected,
            build_selectable_catalog,
            restore_all_device_data,
            restore_selected,
        )

        probe = inv.get("primary_probe") or probe_connected_device()
        device_id = ""
        if probe:
            st.markdown(
                f"<div class='cs-card'><span class='cs-status-ok'>●</span> "
                f"<b>{probe.get('display_name')}</b> ready · {probe.get('model') or ''}</div>",
                unsafe_allow_html=True,
            )
            device_id = str(probe.get("imei") or probe.get("udid") or "unknown-device")

        # —— Selective checkbox catalog + 4 action buttons ——
        catalog = build_selectable_catalog(device_id=device_id or "354345290021725")
        if "sel_backup_ids" not in st.session_state:
            st.session_state["sel_backup_ids"] = list(
                catalog.get("saved_ids") or catalog.get("default_ids") or ["photos_videos", "music"]
            )

        g1, g2 = st.columns(2)
        with g1:
            if st.button(
                "Backup Selected Items",
                type="primary",
                use_container_width=True,
                key="bak_selected_items",
                disabled=not st.session_state.get("sel_backup_ids"),
            ):
                res = backup_selected(
                    list(st.session_state.get("sel_backup_ids") or []),
                    device_id=device_id,
                    apple_account_id=_primary_apple_id() or "",
                    background=True,
                )
                if res.get("ok"):
                    _flash_ok("Selected backup started", res.get("message") or "")
                else:
                    _soft_note("Backup selected", res.get("message") or res.get("error") or "Failed")
                st.rerun()
        with g2:
            if st.button(
                "Backup All Device Data",
                type="primary",
                use_container_width=True,
                key="bak_all_device",
            ):
                res = backup_all_device_data(
                    device_id=device_id,
                    apple_account_id=_primary_apple_id() or "",
                )
                if res.get("ok"):
                    _flash_ok("Full backup started", res.get("message") or "")
                else:
                    _soft_note("Backup all", res.get("message") or "Unlock phone and plug USB.")
                st.rerun()

        r1, r2 = st.columns(2)
        with r1:
            if st.button(
                "Restore Selected Data",
                use_container_width=True,
                key="rst_selected_data",
                disabled=not st.session_state.get("sel_backup_ids"),
            ):
                res = restore_selected(
                    list(st.session_state.get("sel_backup_ids") or []),
                    device_id=device_id,
                )
                if res.get("ok"):
                    _flash_ok(
                        "Restore staged on Mac",
                        res.get("message") or res.get("dest") or "",
                        minor=False,
                    )
                else:
                    _soft_note("Restore selected", res.get("message") or "Nothing selected.")
                st.rerun()
        with r2:
            if st.button(
                "Restore All Device Data",
                use_container_width=True,
                key="rst_all_device",
            ):
                st.session_state["confirm_restore_all"] = True
                st.rerun()

        if st.session_state.get("confirm_restore_all"):
            st.warning(
                "Stage a **full restore package** on this Mac from the Cumulous vault? "
                "Vault originals stay safe. This does not wipe your phone automatically."
            )
            ca, cb = st.columns(2)
            with ca:
                if st.button("Yes, stage full restore", type="primary", key="rst_all_yes"):
                    res = restore_all_device_data(device_id=device_id, confirm=True)
                    st.session_state.pop("confirm_restore_all", None)
                    if res.get("ok"):
                        _flash_ok("Full restore staged", res.get("message") or "", minor=False)
                    else:
                        _soft_note("Restore all", res.get("message") or "Failed")
                    st.rerun()
            with cb:
                if st.button("Cancel", key="rst_all_no"):
                    st.session_state.pop("confirm_restore_all", None)
                    st.rerun()

        st.markdown(
            "<div class='cs-muted' style='margin:0.5rem 0 0.25rem 0'>"
            "<b>What to back up / restore</b> — each line shows size · Backup / Restore for that data only"
            "</div>",
            unsafe_allow_html=True,
        )
        chosen: list[str] = []
        for cat in catalog.get("categories") or []:
            cid = cat["id"]
            size_l = cat.get("size_label") or "—"
            parent_on = st.checkbox(
                f"{cat.get('title') or cid}"
                + (f" · {size_l}" if size_l else "")
                + (" ✓" if cat.get("verified") else ""),
                value=cid in st.session_state["sel_backup_ids"]
                or any(
                    x.startswith(cid + ".") for x in st.session_state["sel_backup_ids"]
                ),
                key=f"sel_cat_{cid}",
            )
            if parent_on:
                chosen.append(cid)
            _line_action_row(
                surface="sel",
                line_id=cid,
                title=str(cat.get("title") or cid),
                device_id=device_id,
                apple_id=_primary_apple_id() or "",
                category_id=cid,
            )
            with st.expander(f"Details · {cat.get('title')} · {size_l}", expanded=False):
                for ch in cat.get("children") or []:
                    ch_size = ch.get("size_label") or "—"
                    ch_on = st.checkbox(
                        f"{ch.get('title') or ch['id']} · {ch_size}",
                        value=ch["id"] in st.session_state["sel_backup_ids"] or parent_on,
                        key=f"sel_sub_{ch['id']}",
                        help=ch.get("hint") or "",
                    )
                    if ch_on:
                        chosen.append(ch["id"])
                    parent_cid = cid
                    sub_only = str(ch["id"]).split(".", 1)[-1] if "." in str(ch["id"]) else ""
                    _line_action_row(
                        surface="sel",
                        line_id=ch["id"],
                        title=str(ch.get("title") or ch["id"]),
                        device_id=device_id,
                        apple_id=_primary_apple_id() or "",
                        category_id=parent_cid,
                        subcategory_id=sub_only,
                    )
        if catalog.get("apps"):
            st.caption("Apps")
            for app in (catalog.get("apps") or [])[:40]:
                aid = app["id"]
                a_size = app.get("size_label") or "—"
                a_on = st.checkbox(
                    f"App: {app.get('title') or aid} · {a_size}",
                    value=aid in st.session_state["sel_backup_ids"],
                    key=f"sel_app_{aid}",
                    help=app.get("hint") or app.get("bundle_id") or "",
                )
                if a_on:
                    chosen.append(aid)
                _line_action_row(
                    surface="sel",
                    line_id=aid,
                    title=str(app.get("title") or aid),
                    device_id=device_id,
                    apple_id=_primary_apple_id() or "",
                    category_id=aid,
                )
        st.session_state["sel_backup_ids"] = list(dict.fromkeys(chosen))

        if probe:
            # —— Storage optimization prompt (every backup start) ——
            _render_storage_optimize_backup_gate(device_id=str(device_id))

            # CEO CP: 2FA / challenge paused — auto-unlock backup path
            from cumulous.auth_policy import auth_required_for_backup, verification_paused_message

            if not auth_required_for_backup():
                st.session_state["backup_auth"] = {
                    "code_ok": True,
                    "totp_ok": True,
                    "device_id": device_id,
                    "apple_id": primary or _primary_apple_id() or "",
                    "skipped_2fa": True,
                }
                st.session_state["force_backup_unlocked"] = True
                st.caption(verification_paused_message())
            else:
                # CEO/user confirm before backup request codes
                if st.button("Request backup authorization", use_container_width=True, key="bak_auth"):
                    aid = primary or _primary_apple_id()
                    ch = spawn_challenge_for_apple_account(
                        purpose="backup_request",
                        apple_account_id=aid,
                        include_mac_mini=True,
                    )
                    labels = ch.get("fanout_device_labels") or ch.get("fanout_device_ids") or []
                    st.session_state["backup_auth"] = {
                        "code_ok": False,
                        "challenge_id": ch.get("challenge_id"),
                        "device_id": device_id,
                        "apple_id": aid,
                        "fanout": ch.get("fanout_device_ids") or [],
                        "fanout_labels": labels,
                        "push_results": ch.get("push_results") or [],
                    }
                    st.session_state.pop("backup_dialog_code_display", None)
                    st.session_state["backup_dialog_open"] = True
                    summary = ", ".join(str(x) for x in labels[:8]) if labels else "your Apple devices"
                    _flash_code(
                        ch["code"],
                        title="Backup Authorization",
                        instructions=(
                            "Enter the 4-digit code from your iPhone in the box below. "
                            "It is not shown on this Mac window."
                        ),
                        fanout_summary=summary,
                        dialog="backup",
                    )
                    set_status("backup_auth", "running", message="Waiting for 4-digit code…")
                    st.rerun()

            auth = st.session_state.get("backup_auth") or {}
            if auth_required_for_backup() and auth and not auth.get("code_ok"):
                # Centered Backup Authorization window with large input + top-left red close
                if st.session_state.get("backup_dialog_open", True):
                    _backup_auth_dialog()
                if _esc_button("bak_esc"):
                    _dismiss_backup_auth_dialog()
                    st.rerun()
                st.markdown("##### Or enter code here")
                code_in = st.text_input(
                    "4-digit authorization",
                    max_chars=4,
                    key="bak_code",
                    placeholder="••••",
                )
                if st.button("Verify & continue", type="primary", key="bak_verify"):
                    if verify_challenge(code_in, purpose="backup_request"):
                        auth["code_ok"] = True
                        st.session_state["backup_auth"] = auth
                        st.session_state["backup_dialog_open"] = False
                        clear_flashes(st)
                        set_status("backup_auth", "ok", message="Authorized")
                        _flash_ok("Backup Authorized", "2FA next, then backup runs.")
                        st.rerun()
                    else:
                        set_status("backup_auth", "error", message="Code rejected")
                        _soft_note("Needs a moment", "Invalid or expired code.")
                labels = auth.get("fanout_labels") or auth.get("fanout") or []
                if labels:
                    st.caption("Devices notified: " + ", ".join(str(x) for x in labels[:12]))
                render_action_badge(st, "backup_auth")

            if auth_required_for_backup() and auth.get("code_ok") and not auth.get("totp_ok"):
                ensure_account_2fa(auth.get("apple_id") or primary)
                totp = st.text_input("6-digit 2FA", max_chars=6, key="bak_totp")
                if st.button("Verify 2FA", type="primary", key="bak_totp_btn"):
                    if verify_account_2fa(auth.get("apple_id") or primary, totp):
                        auth["totp_ok"] = True
                        st.session_state["backup_auth"] = auth
                        set_status("backup_auth", "ok", message="2FA OK — ready to backup")
                        _flash_ok("2FA OK", "Start secure backup.")
                        st.rerun()
                    else:
                        _soft_note("Needs a moment", "That security code wasn’t accepted.")

            if auth.get("totp_ok") or st.session_state.get("force_backup_unlocked") or not auth_required_for_backup():
                if not st.session_state.get("storage_opt_answered"):
                    st.caption("Answer the storage optimization question above before starting backup.")
                if st.button(
                    "Start secure local backup",
                    type="primary",
                    use_container_width=True,
                    key="bak_go",
                    disabled=not st.session_state.get("storage_opt_answered"),
                ):
                    # Optional pre-backup storage pass already handled by gate when Yes chosen
                    if st.session_state.get("storage_opt_run_pending"):
                        from cumulous.storage_optimize import execute_optimization, load_opt_state

                        with st.spinner("Freeing safe space on the iPhone first…"):
                            digs = (load_opt_state().get("last_plan") or {}).get("digests") or []
                            opt = execute_optimization(
                                device_id=str(device_id),
                                mode=st.session_state.get("storage_opt_mode") or "balanced",
                                source="mac",
                                digests=digs,
                            )
                        st.session_state["storage_opt_run_pending"] = False
                        if opt.get("ok"):
                            _flash_ok("Storage optimized", opt.get("message") or "")
                        else:
                            _soft_note("Storage pass paused", opt.get("message") or "Continuing with backup.")
                    with st.spinner("Backing up securely — keep phone unlocked and plugged in…"):
                        res = secure_backup_device(
                            device_id,
                            apple_account_id=primary or "",
                            display_name=probe.get("display_name") or "",
                            run_full_idevice=True,
                            action_id="backup_device",
                        )
                    if res.get("ok"):
                        n = int(res.get("file_count") or 0)
                        _flash_ok(
                            "Backup complete",
                            f"{n} items saved" if n else "Saved securely",
                            minor=False,
                        )
                    else:
                        _soft_note("Backup paused", res.get("error") or "Will retry when the phone is ready.")
                    st.rerun()
                render_action_badge(st, "backup_device")
                st.caption("Encrypted vault on ExternalSSD when mounted. Phone stays unlocked for full system pull.")
        else:
            _soft_note("Heads up", "Connect and Trust your iPhone, then Scan for iPhone on Home.")
            st.caption("ROB IPHONE (2) must appear as Connected before Backup Now.")

        # —— Music + Podcasts dual-mirror (playlists untouched on device) ——
        st.markdown("<div class='cs-header' style='margin-top:1rem'>Music & Podcasts</div>", unsafe_allow_html=True)
        from cumulous.music_offload import (
            freeable_music_items,
            free_music_on_device_usb,
            library_status as music_library_status,
            music_harvest_progress,
            start_music_harvest,
        )
        from cumulous.photo_offload import usb_device_present as _usb_music

        mprog = music_harvest_progress()
        mharv = mprog.get("harvest") or {}
        mlib = music_library_status()
        mby = mlib.get("by_class") or {}
        mfree = freeable_music_items()
        musb = _usb_music()
        free_gb = (mprog.get("device_free") or {}).get("free_gb")
        st.markdown(
            f"<div class='cs-card'>"
            f"<b>{mlib.get('mirrored_dual_count') or 0}</b> dual-mirrored · "
            f"<b>{mlib.get('indexed_count') or 0}</b> in vault<br>"
            f"<span class='cs-muted'>"
            f"Cache {(mby.get('cache') or {}).get('count', 0)} · "
            f"Cloud downloads {(mby.get('cloud_eligible') or {}).get('count', 0)} · "
            f"Local-only {(mby.get('local_only') or {}).get('count', 0)} (kept on phone) · "
            f"Playlists {(mby.get('playlist') or {}).get('count', 0)} (untouched on phone) · "
            f"Podcasts {(mby.get('podcast_media') or {}).get('count', 0)}"
            f"</span>"
            f"{('<br><span class=\"cs-status-ok\">● Music backup running… '
                + str(mharv.get('mirrored') or 0) + ' new</span>') if mharv.get('status') == 'running' else ''}"
            f"<br><span class='cs-muted'>Phone free: {free_gb if free_gb is not None else '—'} GB · "
            f"{len(mfree)} freeable items after dual-verify "
            f"(never playlists or local-only tracks)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        mb1, mb2, mb3 = st.columns(3)
        with mb1:
            if st.button("Back up Music now", type="primary", use_container_width=True, key="music_harvest_usb"):
                if not musb.get("usb"):
                    _soft_note("Connect iPhone", "Plug in with USB, unlock, and tap Trust.")
                else:
                    probe_m = musb.get("probe") or {}
                    did_m = probe_m.get("imei") or probe_m.get("device_id") or probe_m.get("udid") or ""
                    set_status("music_harvest", "running", message="Backing up Music…")
                    start_music_harvest(
                        device_id=str(did_m),
                        udid=str(probe_m.get("udid") or ""),
                        apple_account_id=_primary_apple_id() or "",
                        limit=None,
                    )
                    _flash_ok(
                        "Music backup started",
                        "All Music + Podcasts dual-mirror to this Mac + Nextcloud. "
                        "Playlists stay on your phone untouched.",
                    )
                st.rerun()
        with mb2:
            if st.button(
                f"Free Music space ({len(mfree)})",
                use_container_width=True,
                key="music_free_usb",
                help="Removes Cache, cloud-eligible Downloads, and podcast media only. "
                "Playlists and local-only tracks stay on the phone.",
            ):
                st.session_state["confirm_music_free"] = True
                st.rerun()
        with mb3:
            if st.button("Refresh Music status", use_container_width=True, key="music_status_refresh"):
                st.rerun()
        render_action_badge(st, "music_harvest")
        if st.session_state.get("confirm_music_free"):
            st.warning(
                "Frees dual-backed-up Cache, Apple Music offline packs, and podcast audio from the phone. "
                "**Playlists stay untouched.** Local-only tracks stay on the phone. "
                "Photos are not touched. USB required."
            )
            mfa, mfb = st.columns(2)
            with mfa:
                if st.button("Yes, free Music/Podcast space", type="primary", key="music_free_yes"):
                    res_f = free_music_on_device_usb(dry_run=False)
                    st.session_state.pop("confirm_music_free", None)
                    if res_f.get("ok") or int(res_f.get("removed") or 0) > 0:
                        gb = (res_f.get("bytes_removed") or 0) / 1e9
                        _flash_ok(
                            "Music space freed",
                            f"{res_f.get('removed', 0)} items (~{gb:.2f} GB). "
                            "Playlists and local-only tracks left on phone.",
                            minor=False,
                        )
                    else:
                        _soft_note(
                            "Couldn’t free yet",
                            res_f.get("message")
                            or res_f.get("error")
                            or "Finish Music backup first, or plug in USB.",
                        )
                    st.rerun()
            with mfb:
                if st.button("Cancel", key="music_free_no"):
                    st.session_state.pop("confirm_music_free", None)
                    st.rerun()

    # —— Install on Phones ——
    if tab == "install":
        st.markdown("<div class='cs-header'>Install Cumulous App</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='cs-card cs-muted'>"
            "<b>Cumulous is a real app</b> (SwiftUI project + full-screen app shell). "
            "New USB devices get an install push automatically. "
            "Each device chooses <b>Home Screen</b> or <b>App Library</b>."
            "</div>",
            unsafe_allow_html=True,
        )

        if st.button("Push Cumulous to connected iPhone", type="primary", use_container_width=True, key="push_app_connected"):
            set_status("push_app", "running", message="Pushing install…")
            res = auto_invite_connected_device(force=True)
            usb = try_usb_install_ipa((inv.get("primary_probe") or {}).get("udid"))
            if res.get("ok"):
                set_status(
                    "push_app",
                    "ok",
                    message="Install push sent",
                    detail=(res.get("message") or "")[:140],
                )
                name = ((res.get("invite") or {}).get("display_name") or "iPhone")
                _flash_ok("Install sent", name)
                st.markdown(
                    "<div class='cs-card'><b>Open Safari on the phone</b><br>"
                    "<span class='cs-muted'>Choose Home Screen or App Library when asked. "
                    "If nothing appears, open the install link from Settings → Install.</span></div>",
                    unsafe_allow_html=True,
                )
                if usb and usb.get("ok"):
                    st.caption("USB install finished.")
                elif usb:
                    st.caption("Web Clip install is ready (native IPA when built).")
            else:
                set_status("push_app", "error", message=res.get("error") or "No phone")
                _soft_note("No phone", "Plug in and unlock the iPhone, then try again.")
            st.rerun()
        render_action_badge(st, "push_app")

        if st.button("Invite all devices on my Apple Account", use_container_width=True, key="invite_all_acct"):
            set_status("install_invite", "running", message="Sending…")
            res = invite_all_apple_account_devices(primary or "")
            n = int(res.get("count") or 0)
            _badge_only("install_invite", "ok", f"Invited {n} device(s)")
            _flash_ok("Invites sent", f"{n} device(s)")
            st.rerun()
        render_action_badge(st, "install_invite")

        probe_i = inv.get("primary_probe") or probe_connected_device()
        if probe_i:
            st.markdown(
                f"<div class='cs-card'><span class='cs-status-ok'>●</span> USB: "
                f"<b>{probe_i.get('display_name')}</b> connected — new devices auto-receive install push</div>",
                unsafe_allow_html=True,
            )
        st.caption(f"App (Photos in-app): {best_app_url()}")
        st.caption(f"Install chooser: {best_portal_url()}")
        st.caption("Native SwiftUI: ios/Cumulous.xcodeproj — open in Xcode to run on device / archive IPA")

    # —— Settings ——
    if tab == "settings":
        st.markdown("<div class='cs-header'>Settings</div>", unsafe_allow_html=True)
        data = load_secrets()
        settings = data.get("settings") or {}
        hours = st.select_slider(
            "Updates occur",
            options=[6, 12, 18, 24],
            value=int(settings.get("schedule_hours") or 12),
        )
        persistent = st.toggle("Persistent backups", value=bool(settings.get("persistent_backups", True)))
        schedule_mode = st.selectbox(
            "Schedule mode",
            ["standard", "persistent"],
            index=0 if settings.get("schedule_mode") == "standard" else 1,
        )
        midnight_mode = st.selectbox(
            "Midnight backup mode",
            ["standard", "persistent"],
            index=0 if settings.get("midnight_mode") == "standard" else 1,
        )
        change_mode = st.selectbox(
            "On-change backup mode",
            ["standard", "persistent"],
            index=0 if settings.get("change_driven_mode") == "standard" else 1,
        )
        st.markdown("<div class='cs-header'>Photos / videos (preferences only)</div>", unsafe_allow_html=True)
        photo_prefs = load_photo_prefs()
        free_phone = st.toggle(
            "Free iPhone space after dual mirror (HDD + Nextcloud both verified)",
            value=bool(photo_prefs.get("free_phone_storage_after_backup", True)),
            help=(
                "When ON, originals are removed from the phone only after both copies exist. "
                "Run photo backup from the Photos tab."
            ),
        )
        from cumulous.photo_offload import set_download_and_keep_originals

        keep_toggle = st.toggle(
            "Download and Keep Originals (after initial backup)",
            value=bool(photo_prefs.get("download_and_keep_originals")),
            help=(
                "When on, new photos stay on the iPhone and still get added to Cumulous. "
                "Previous backups are never removed by later runs. Applied when you Save settings."
            ),
            key="set_keep_originals_toggle",
        )
        wifi_only = st.toggle(
            "Photo offload Wi‑Fi only (recommended)",
            value=bool(photo_prefs.get("wifi_only_offload", True)),
        )
        cell_ok = st.toggle(
            "Allow photo offload on cellular",
            value=bool(photo_prefs.get("cellular_offload_allowed", False)),
        )
        interval = st.select_slider(
            "Photo sync interval (minutes)",
            options=[15, 30, 60, 120, 360],
            value=int(photo_prefs.get("sync_interval_minutes") or 30),
        )

        st.markdown("<div class='cs-header'>Network backup (Wi‑Fi / Cellular)</div>", unsafe_allow_html=True)
        eps = backup_endpoints()
        st.markdown(
            f"<div class='cs-card cs-muted'>"
            f"<b>USB</b> — best for full system backup<br>"
            f"<b>Wi‑Fi</b> — API: {', '.join((eps.get('wifi_lan') or {}).get('api') or ['—'])}<br>"
            f"<b>Cellular</b> — Tailscale: {(eps.get('cellular_or_remote') or {}).get('api') or 'install Tailscale'}"
            f"</div>",
            unsafe_allow_html=True,
        )
        net = load_network_prefs()
        wifi_en = st.toggle("Enable Wi‑Fi backup", value=bool(net.get("wifi_enabled", True)))
        cell_en = st.toggle("Enable cellular backup (via Tailscale)", value=bool(net.get("cellular_enabled", True)))
        if st.button("Check wireless devices", key="wifi_check"):
            hint = enable_wifi_sync_hint()
            set_status(
                "wifi_check",
                "ok" if hint.get("wifi_devices_seen") else "error",
                message=f"{len(hint.get('wifi_devices_seen') or [])} Wi‑Fi device(s)",
                detail=", ".join(hint.get("wifi_devices_seen") or []) or "None — USB pair once, same Wi‑Fi",
            )
            st.rerun()
        render_action_badge(st, "wifi_check")

        if st.button("Save settings", key="save_set"):
            set_status("save_settings", "running", message="Saving…")
            secrets = load_secrets()
            secrets.setdefault("settings", {})
            secrets["settings"].update(
                {
                    "schedule_hours": hours,
                    "persistent_backups": persistent,
                    "schedule_mode": schedule_mode,
                    "midnight_mode": midnight_mode,
                    "change_driven_mode": change_mode,
                }
            )
            from cumulous.auth import save_secrets

            save_secrets(secrets)
            record_setup_choice(free_phone_storage=free_phone)
            pp = load_photo_prefs()
            pp.update(
                {
                    "wifi_only_offload": wifi_only,
                    "cellular_offload_allowed": cell_ok,
                    "sync_interval_minutes": interval,
                    "host_originals_on_hdd": True,
                    "host_originals_on_nextcloud": True,
                    "require_dual_mirror_before_delete": True,
                    "free_phone_storage_after_backup": free_phone,
                    "download_and_keep_originals": bool(keep_toggle),
                    "add_only_vault": True,
                }
            )
            if keep_toggle:
                pp["free_phone_storage_after_backup"] = False
            save_photo_prefs(pp)
            if keep_toggle:
                set_download_and_keep_originals(True)
            save_network_prefs(
                {
                    **net,
                    "wifi_enabled": wifi_en,
                    "cellular_enabled": cell_en,
                }
            )
            _badge_only("save_settings", "ok", "Settings saved")
            _flash_ok("Settings saved")
            st.rerun()
        render_action_badge(st, "save_settings")
        st.caption("Individual user logins removed. Access is by Apple Account + device + Confirm User.")

    # —— CEO Override ——
    if tab == "ceo":
        st.markdown("<div class='cs-header'>CEO Override</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='cs-card cs-muted'>Generate a 30‑minute code for recovery. "
            "Codes go to CEO devices and the Apple Account under challenge. "
            "2FA secrets per Apple Account live only in local <b>2xsecrets</b>.</div>",
            unsafe_allow_html=True,
        )
        if st.button("Generate Code", type="primary", use_container_width=True):
            aid = primary or "BEARACCOUNT"
            ch = spawn_challenge_for_apple_account(
                purpose="ceo_override",
                apple_account_id=aid,
                include_mac_mini=True,
            )
            # also keep legacy union path
            if not ch.get("fanout_device_ids"):
                ch = spawn_challenge_for_user(purpose="ceo_override", requesting_user_id="BEARACCOUNT")
            _flash_code(ch["code"], title="CEO Override Code")
            st.session_state["last_code_fanout"] = ch.get("fanout_device_ids") or []
            set_status("ceo_code", "ok", message="Code generated", detail=f"{len(ch.get('fanout_device_ids') or [])} devices")
            st.rerun()
        render_action_badge(st, "ceo_code")
        if st.session_state.get("last_code_fanout") is not None:
            fan = st.session_state["last_code_fanout"]
            st.caption("Devices notified: " + (", ".join(fan) if fan else "on-screen only"))

        if _esc_button("ceo_esc_flash"):
            clear_flashes(st)
            st.rerun()

        if st.button("Write CEOOVERRIDE.md", use_container_width=True):
            write_ceo_override_md()
            _badge_only("ceo_md", "ok", "Notes written")
            _flash_ok("Notes written")
            st.rerun()
        render_action_badge(st, "ceo_md")

        with st.expander("CEO only · 2xsecrets (Apple Account 2FA)"):
            secrets = read_2xsecrets_for_ceo()
            accounts = secrets.get("accounts") or {}
            if not accounts:
                st.caption("No Apple Account 2FA secrets yet. Register a device or sync account.")
            for aid, rec in accounts.items():
                st.markdown(f"**{aid}**")
                st.code(rec.get("totp_secret") or "—")
                st.caption("Keep private. File: ~/.cumulous/2xsecrets")

    # Single mount for Confirm User (Home + Backups both set confirm_flow)
    if st.session_state.get("confirm_flow"):
        st.divider()
        _render_confirm_user_panel()


if __name__ == "__main__":
    main()
