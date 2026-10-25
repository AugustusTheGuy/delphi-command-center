"""Apple-like feedback: inline badges, quiet toasts, rare primary sheets.

Success feedback must be plain English (never raw dicts/paths/codes in UI).
Dismiss: Streamlit-native buttons + backdrop; JS is progressive enhancement only.
"""

from __future__ import annotations

import html
import subprocess
import time
from typing import Any, Literal

Priority = Literal["toast", "sheet", "banner"]

# Dark elevated success (iOS feel) — not white paper
GREEN_CHECK_SVG = """
<svg width="40" height="40" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle cx="20" cy="20" r="18" fill="rgba(48,209,88,0.15)" stroke="#30d158" stroke-width="1.5"/>
  <path d="M12 21 L17.5 26.5 L28 14" fill="none" stroke="#30d158" stroke-width="2.5"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def queue_flash(st_module, kind: str, title: str, detail: str = "", **extra: Any) -> None:
    st = st_module
    flashes = list(st.session_state.get("cumulous_flashes") or [])
    flashes.append(
        {
            "kind": kind,
            "title": title,
            "detail": detail,
            "created_at": time.time(),
            **extra,
        }
    )
    # Cap queue — never pile up modals
    st.session_state["cumulous_flashes"] = flashes[-4:]


def clear_flashes(st_module) -> None:
    st_module.session_state["cumulous_flashes"] = []


def toast_ok(st_module, title: str, detail: str = "") -> None:
    """Non-blocking completion (most actions)."""
    from cumulous.ux_copy import friendly_message

    queue_flash(
        st_module,
        "toast",
        friendly_message(title, fallback=title or "Completed"),
        friendly_message(detail, fallback=detail or "", allow_empty=True),
        priority="toast",
        auto_dismiss_sec=2.8,
    )


def toast_fail(st_module, title: str = "Couldn’t finish", detail: str = "") -> None:
    from cumulous.ux_copy import friendly_message

    queue_flash(
        st_module,
        "toast_fail",
        friendly_message(title, fallback="Couldn’t finish"),
        friendly_message(detail, fallback=detail or "", allow_empty=True),
        priority="toast",
        auto_dismiss_sec=3.5,
    )


def sheet_ok(st_module, title: str, detail: str = "") -> None:
    """Rare primary completion sheet (restore complete, etc.)."""
    from cumulous.ux_copy import friendly_message

    queue_flash(
        st_module,
        "sheet",
        friendly_message(title, fallback="Completed"),
        friendly_message(detail, fallback=detail or "", allow_empty=True),
        priority="sheet",
    )


def inject_modal_css(st_module) -> None:
    from cumulous.theme import css_root_variables

    # Concatenate (not f-string) so CSS braces stay literal.
    css = (
        "<style>\n"
        "/* Cumulous · matte black · thin metallic silver · Apple blue / deny red */\n"
        + css_root_variables()
        + """
html, body, .stApp, [data-testid="stAppViewContainer"] {
  background: var(--cs-bg) !important;
  color: var(--cs-text-shine) !important;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
    "Helvetica Neue", sans-serif !important;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
.stApp {
  background:
    radial-gradient(ellipse 120% 80% at 50% -20%, rgba(200,202,210,0.07), transparent 55%),
    var(--cs-bg) !important;
}
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
div[data-testid="stException"],
div[data-testid="stAlert"],
.stException,
.stAlert { display: none !important; }
.block-container {
  padding-top: 0.75rem !important;
  padding-bottom: 3rem !important;
  max-width: 760px !important;
}
h1, h2, h3, h4, p, label, span, .stMarkdown {
  color: var(--cs-text-shine) !important;
}
h1, h2, h3 {
  font-weight: 600 !important;
  letter-spacing: -0.03em;
  text-shadow: 0 0 24px rgba(255,255,255,0.18);
}
[data-testid="stSidebar"] { background: var(--cs-elevated) !important; border-right: 1px solid var(--cs-line) !important; }
div[data-baseweb="tab-list"] {
  gap: 2px;
  background: var(--cs-elevated);
  border: 1px solid var(--cs-line);
  border-radius: 14px;
  padding: 3px;
  backdrop-filter: blur(20px);
}
button[data-baseweb="tab"] {
  color: var(--cs-muted) !important;
  border-radius: 11px !important;
  font-size: 0.82rem !important;
  font-weight: 500 !important;
  letter-spacing: -0.01em;
  padding: 0.45rem 0.7rem !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
  background: var(--cs-silver-soft) !important;
  color: var(--cs-text-shine) !important;
  box-shadow: inset 0 0 0 1px var(--cs-line-strong);
  text-shadow: 0 0 12px rgba(255,255,255,0.2);
}
.stTextInput input, .stTextInput > div > div > input {
  background: var(--cs-card-solid) !important;
  color: var(--cs-text-shine) !important;
  border: 1px solid var(--cs-line) !important;
  border-radius: 12px !important;
  box-shadow: none !important;
}
.stTextInput input:focus {
  border-color: var(--cs-line-strong) !important;
  box-shadow: 0 0 0 1px var(--cs-silver-soft) !important;
}
.cs-pin-wrap input, div[data-testid="stDialog"] .cs-pin-field input,
div[data-testid="stDialog"] input[type="text"] {
  max-width: 7.5rem !important;
  width: 7.5rem !important;
  margin: 0 auto !important;
  font-size: 1.55rem !important;
  letter-spacing: 0.42em !important;
  text-align: center !important;
  font-weight: 600 !important;
  font-variant-numeric: tabular-nums !important;
  padding: 0.6rem 0.45rem !important;
  color: var(--cs-text-shine) !important;
  border: 1px solid var(--cs-line) !important;
  background: #121212 !important;
}
.stButton > button {
  background: linear-gradient(180deg, #2c2c2e 0%, #1c1c1e 100%) !important;
  color: var(--cs-text-shine) !important;
  border: 1px solid var(--cs-line) !important;
  border-radius: 14px !important;
  font-weight: 600 !important;
  padding: 0.6rem 1.15rem !important;
  letter-spacing: -0.01em;
  min-height: 44px !important;
  transition: filter 0.12s ease, border-color 0.12s ease;
  box-shadow: 0 1px 0 rgba(255,255,255,0.05) inset;
}
.stButton > button:hover {
  filter: brightness(1.08);
  border-color: var(--cs-line-strong) !important;
}
/* Glassy shine: blue action buttons (primary / deny-class / HTML helpers) */
button[kind="primary"],
.stButton > button.cs-btn-deny,
button.cs-btn-deny,
.cs-btn-apple-blue,
.cs-btn-glass-blue {
  background:
    linear-gradient(180deg, rgba(255,255,255,0.38) 0%, rgba(255,255,255,0.12) 32%, rgba(255,255,255,0) 55%),
    linear-gradient(180deg, #1a8fff 0%, #007AFF 48%, #0062cc 100%) !important;
  color: #ffffff !important;
  border: 1px solid rgba(255,255,255,0.28) !important;
  box-shadow:
    0 1px 0 rgba(255,255,255,0.45) inset,
    0 -1px 0 rgba(0,40,100,0.25) inset,
    0 6px 18px rgba(0,122,255,0.32),
    0 0 0 0.5px rgba(0,122,255,0.4) !important;
  backdrop-filter: saturate(1.2) blur(10px);
  -webkit-backdrop-filter: saturate(1.2) blur(10px);
}
button[kind="primary"]:hover,
.stButton > button.cs-btn-deny:hover,
button.cs-btn-deny:hover,
.cs-btn-apple-blue:hover,
.cs-btn-glass-blue:hover {
  background:
    linear-gradient(180deg, rgba(255,255,255,0.48) 0%, rgba(255,255,255,0.16) 34%, rgba(255,255,255,0) 58%),
    linear-gradient(180deg, #2a98ff 0%, #0a84ff 48%, #0066d6 100%) !important;
  filter: brightness(1.04);
}
button[kind="secondary"] {
  background: rgba(14,14,14,0.95) !important;
  color: var(--cs-silver) !important;
  border: 1px solid var(--cs-line) !important;
}
/* In-tab red only (ESC etc.) — 15% smaller + glass. Traffic lights stay 14px. */
.stButton > button.cs-btn-red-inapp,
button.cs-btn-red-inapp,
.cs-btn-apple-red,
.cs-btn-glass-red,
button[kind="secondary"][title="Cancel and close"] {
  background:
    linear-gradient(180deg, rgba(255,255,255,0.36) 0%, rgba(255,255,255,0.1) 32%, rgba(255,255,255,0) 55%),
    linear-gradient(180deg, #ff6b63 0%, #FF3B30 48%, #d70015 100%) !important;
  color: #ffffff !important;
  border: 1px solid rgba(255,255,255,0.26) !important;
  box-shadow:
    0 1px 0 rgba(255,255,255,0.4) inset,
    0 -1px 0 rgba(80,0,0,0.22) inset,
    0 6px 16px rgba(255,59,48,0.28),
    0 0 0 0.5px rgba(255,59,48,0.35) !important;
  backdrop-filter: saturate(1.15) blur(10px);
  -webkit-backdrop-filter: saturate(1.15) blur(10px);
  min-height: 37px !important;
  padding: 0.51rem 0.98rem !important;
  font-size: 0.9rem !important;
  border-radius: 12px !important;
  font-weight: 700 !important;
  letter-spacing: 0.04em;
}
.stButton > button.cs-btn-red-inapp:hover,
button.cs-btn-red-inapp:hover,
.cs-btn-apple-red:hover,
.cs-btn-glass-red:hover,
button[kind="secondary"][title="Cancel and close"]:hover {
  background:
    linear-gradient(180deg, rgba(255,255,255,0.46) 0%, rgba(255,255,255,0.14) 34%, rgba(255,255,255,0) 58%),
    linear-gradient(180deg, #ff7a72 0%, #ff453a 48%, #c41e1e 100%) !important;
  filter: brightness(1.04);
}
[data-testid="stMetric"] {
  background: var(--cs-card);
  border: 1px solid var(--cs-line);
  border-radius: 16px;
  padding: 0.75rem 0.9rem;
}
[data-testid="stMetricLabel"] { color: var(--cs-muted) !important; font-size: 0.72rem !important; }
[data-testid="stMetricValue"] {
  color: var(--cs-text-shine) !important;
  font-weight: 600 !important;
  text-shadow: 0 0 18px rgba(255,255,255,0.22);
}
.cs-card {
  background: var(--cs-card);
  border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius);
  padding: 1.1rem 1.2rem;
  margin-bottom: 0.7rem;
  backdrop-filter: blur(28px);
  box-shadow: 0 16px 48px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.04);
}
.cs-muted { color: var(--cs-muted) !important; font-size: 0.88rem; line-height: 1.45; }
.cs-faint { color: var(--cs-faint) !important; font-size: 0.78rem; }
.cs-header {
  font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.14em;
  color: var(--cs-silver) !important; margin: 1.1rem 0 0.55rem; font-weight: 600;
  opacity: 0.95;
  text-shadow: 0 0 14px rgba(255,255,255,0.15);
}
.cs-status-ok { color: var(--cs-blue) !important; }
.cs-status-warn { color: var(--cs-amber) !important; }
.cs-status-err { color: var(--cs-red) !important; }
/* Backup progress mini-window */
.cs-progress-backdrop {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.52);
  display: flex; align-items: center; justify-content: center;
  backdrop-filter: blur(6px);
}
.cs-progress-sheet {
  background: #141416;
  border: 1px solid var(--cs-line);
  border-radius: 18px;
  padding: 1.15rem 1.25rem 1.1rem;
  min-width: 360px; max-width: 440px; width: min(92vw, 440px);
  box-shadow: 0 28px 90px rgba(0,0,0,0.65), 0 0 0 1px rgba(255,255,255,0.04) inset;
  position: relative;
}
.cs-progress-pct {
  font-size: 1.65rem; font-weight: 600; letter-spacing: -0.03em;
  color: var(--cs-text-shine) !important;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 0 20px rgba(255,255,255,0.25);
}
.cs-progress-track {
  height: 10px; background: rgba(255,255,255,0.08); border-radius: 999px; overflow: hidden;
  border: 1px solid var(--cs-line);
}
.cs-progress-fill {
  height: 100%; border-radius: 999px;
  background: linear-gradient(90deg, var(--cs-progress-a), var(--cs-progress-b));
  box-shadow: 0 0 14px rgba(0,122,255,0.45);
  transition: width 0.45s ease;
}
/* Apple-style compact 4-digit + map card */
.cs-pin-card {
  display: flex; justify-content: center; margin: 0.75rem auto 1rem;
  max-width: 260px;
}
.cs-pin-card-inner {
  width: 100%;
  min-height: 360px;
  background: #1c1c1e;
  border: 1px solid var(--cs-line);
  border-radius: 18px;
  padding: 1rem 0.85rem 0.9rem;
  box-shadow: 0 20px 50px rgba(0,0,0,0.55);
  text-align: center;
}
.cs-pin-title {
  font-size: 0.78rem; font-weight: 600; color: #fff !important;
  letter-spacing: -0.01em; margin-bottom: 0.15rem;
  text-shadow: 0 0 12px rgba(255,255,255,0.25);
}
.cs-pin-sub { font-size: 0.68rem; color: #c7c7cc !important; margin-bottom: 0.75rem; }
.cs-pin-boxes { display: flex; gap: 8px; justify-content: center; margin: 0.5rem 0 0.65rem; }
.cs-pin-box {
  width: 36px; height: 44px; border-radius: 8px;
  background: #0e0e0e; border: 1px solid var(--cs-line);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 1.35rem; font-weight: 600; color: #fff !important;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 0 10px rgba(255,255,255,0.25);
}
.cs-pin-place {
  font-size: 0.72rem; color: #e8e8ed !important; margin: 0.35rem 0 0.5rem;
  font-weight: 500;
}
.cs-pin-map-wrap {
  width: 100%; max-width: 240px; margin: 0 auto;
  border-radius: 10px; overflow: hidden;
  border: 1px solid var(--cs-line);
  height: 110px; background: #1a1a1c;
}
.cs-pin-map-third {
  height: 130px !important;
  max-width: 100% !important;
  margin-top: 0.35rem;
}
.cs-pin-map { width: 100%; height: 100%; object-fit: cover; display: block; }
.cs-pin-map-empty {
  display: flex; align-items: center; justify-content: center;
  color: #8e8e93; font-size: 0.7rem; min-height: 110px;
}
.cs-pin-ttl { font-size: 0.62rem; color: #a1a1a6 !important; margin-top: 0.55rem; }
.cs-pin-boxes-hidden {
  font-size: 0.78rem; color: #c7c7cc; padding: 0.5rem 0;
}
.cs-btn-apple-blue {
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 12px !important;
  font-weight: 600 !important;
  font-size: 0.92rem !important;
  padding: 0.55rem 1.1rem !important;
  min-height: 36px !important;
  letter-spacing: -0.01em;
  cursor: pointer;
}
/* In-tab red HTML control — size/glass from .cs-btn-apple-red rules above */
.cs-btn-apple-red {
  display: inline-flex; align-items: center; justify-content: center;
  cursor: pointer;
}
.cs-pin-actions {
  display: flex; justify-content: flex-end; align-items: center;
  width: 100%; max-width: 240px; margin: 0.65rem auto 0;
  gap: 0.5rem;
}
div[data-testid="stDialog"] button[kind="primary"] {
  border-radius: 12px !important;
  font-weight: 600 !important;
}
.cs-badge {
  display: inline-block; font-size: 0.65rem; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  padding: 0.22rem 0.55rem; border-radius: 999px;
}
.cs-acct {
  background: linear-gradient(165deg, rgba(28,28,30,0.95) 0%, rgba(12,12,14,0.98) 100%);
  border: 1px solid var(--cs-line); border-radius: 22px;
  padding: 1.2rem 1.3rem; margin-bottom: 1rem;
}
.cs-dev {
  background: rgba(10,10,12,0.8); border: 1px solid var(--cs-line);
  border-radius: 16px; padding: 0.95rem 1.1rem; margin: 0.5rem 0;
}
.cs-dev h4 { margin: 0 0 0.3rem 0; font-size: 1rem; font-weight: 600; color: #fff; letter-spacing: -0.02em; }
.cs-hero { text-align: center; margin: 0.25rem 0 1.1rem; }
.cs-hero-title {
  font-size: 1.55rem; font-weight: 600; letter-spacing: -0.035em; color: var(--cs-text);
  text-shadow: 0 0 20px rgba(255,255,255,0.15);
}
.cs-hero-sub { color: var(--cs-muted); font-size: 0.9rem; margin-top: 0.25rem; }
.cs-chip {
  display: inline-flex; align-items: center; gap: 0.35rem;
  font-size: 0.72rem; font-weight: 500; color: var(--cs-muted);
  background: rgba(255,255,255,0.04); border: 1px solid var(--cs-line);
  border-radius: 999px; padding: 0.28rem 0.65rem;
}
.cs-chip.ok { color: var(--cs-blue); border-color: rgba(0,122,255,0.35); }

/* —— Home Status tiles: label colon + traffic-light text + box glow —— */
.cs-status-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.65rem;
  margin: 0 0 0.85rem 0;
}
@media (max-width: 720px) {
  .cs-status-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.cs-status-tile {
  position: relative;
  border-radius: 16px;
  padding: 0.85rem 0.9rem 0.9rem;
  background: linear-gradient(165deg, rgba(18,18,20,0.96) 0%, rgba(8,8,10,0.98) 100%);
  overflow: hidden;
}
.cs-status-tile .cs-status-label {
  display: block;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: none;
  color: var(--cs-faint);
  margin-bottom: 0.35rem;
}
.cs-status-tile .cs-status-value {
  display: inline-block;
  font-size: 1.05rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.2;
}
/* Affirmed: Apple traffic-light green text + steady 5× bright green glow */
.cs-status-tile.ok {
  border: 1px solid rgba(52, 199, 89, 0.55);
  box-shadow:
    0 0 6px rgba(52, 199, 89, 0.55),
    0 0 14px rgba(48, 209, 88, 0.45),
    0 0 28px rgba(48, 209, 88, 0.35),
    0 0 48px rgba(48, 209, 88, 0.22),
    inset 0 0 18px rgba(48, 209, 88, 0.08);
}
.cs-status-tile.ok .cs-status-value {
  color: #34C759;
  text-shadow:
    0 0 4px rgba(52, 199, 89, 0.95),
    0 0 10px rgba(48, 209, 88, 0.85),
    0 0 22px rgba(48, 209, 88, 0.65),
    0 0 40px rgba(48, 209, 88, 0.45),
    0 0 64px rgba(48, 209, 88, 0.28);
}
/* Unaffirmed: Apple HIG red text + steady 2× dark-red glow */
.cs-status-tile.bad {
  border: 1px solid rgba(255, 59, 48, 0.5);
  box-shadow:
    0 0 5px rgba(255, 59, 48, 0.4),
    0 0 14px rgba(215, 0, 21, 0.28),
    0 0 26px rgba(120, 0, 12, 0.22),
    inset 0 0 14px rgba(80, 0, 8, 0.18);
}
.cs-status-tile.bad .cs-status-value {
  color: #FF3B30;
  text-shadow:
    0 0 3px rgba(255, 59, 48, 0.7),
    0 0 10px rgba(215, 0, 21, 0.45),
    0 0 20px rgba(120, 0, 12, 0.35);
}

/* Live chip: 8× bright green pulse @ 1.25s */
.cs-chip.live-pulse {
  color: #30D158 !important;
  font-weight: 650;
  border-color: rgba(48, 209, 88, 0.65) !important;
  background: rgba(48, 209, 88, 0.1) !important;
  animation: csLivePulse 1.25s ease-in-out infinite;
}
@keyframes csLivePulse {
  0%, 100% {
    box-shadow:
      0 0 4px rgba(48, 209, 88, 0.55),
      0 0 12px rgba(48, 209, 88, 0.4),
      0 0 24px rgba(48, 209, 88, 0.28),
      0 0 40px rgba(48, 209, 88, 0.16);
    text-shadow:
      0 0 4px rgba(48, 209, 88, 0.7),
      0 0 12px rgba(48, 209, 88, 0.45);
  }
  50% {
    box-shadow:
      0 0 10px rgba(48, 209, 88, 0.95),
      0 0 28px rgba(48, 209, 88, 0.85),
      0 0 56px rgba(48, 209, 88, 0.7),
      0 0 90px rgba(48, 209, 88, 0.5),
      0 0 120px rgba(48, 209, 88, 0.32);
    text-shadow:
      0 0 8px rgba(48, 209, 88, 1),
      0 0 22px rgba(48, 209, 88, 0.9),
      0 0 40px rgba(48, 209, 88, 0.7);
  }
}
/* No Connection chip: 3× dark-red pulse @ 1.5s */
.cs-chip.dead-pulse {
  color: #FF3B30 !important;
  font-weight: 650;
  border-color: rgba(255, 59, 48, 0.55) !important;
  background: rgba(80, 0, 8, 0.28) !important;
  animation: csDeadPulse 1.5s ease-in-out infinite;
}
@keyframes csDeadPulse {
  0%, 100% {
    box-shadow:
      0 0 3px rgba(255, 59, 48, 0.35),
      0 0 10px rgba(160, 0, 16, 0.28),
      0 0 18px rgba(80, 0, 8, 0.2);
    text-shadow:
      0 0 3px rgba(255, 59, 48, 0.45),
      0 0 8px rgba(160, 0, 16, 0.3);
  }
  50% {
    box-shadow:
      0 0 8px rgba(255, 59, 48, 0.65),
      0 0 20px rgba(180, 0, 18, 0.5),
      0 0 36px rgba(100, 0, 10, 0.4),
      0 0 52px rgba(60, 0, 6, 0.28);
    text-shadow:
      0 0 6px rgba(255, 59, 48, 0.75),
      0 0 16px rgba(180, 0, 18, 0.5);
  }
}
@media (prefers-reduced-motion: reduce) {
  .cs-chip.live-pulse, .cs-chip.dead-pulse { animation: none !important; }
}
.action-row { display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; margin-top:0.45rem; }
.stCaption, [data-testid="stCaptionContainer"] { color: var(--cs-faint) !important; font-size: 0.78rem !important; }
hr { border-color: var(--cs-line) !important; }

.cs-toast {
  position: relative;
  margin: 0 0 0.75rem 0;
  background: rgba(28,28,30,0.96);
  border: 1px solid var(--cs-line);
  border-radius: 16px;
  padding: 0.85rem 1rem 0.85rem 2.4rem;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  animation: csToastIn 0.2s ease-out;
}
.cs-toast.fail { border-color: rgba(255,59,48,0.35); }
.cs-toast .cs-toast-title { font-weight: 600; font-size: 0.95rem; letter-spacing: -0.02em; color: var(--cs-text); }
.cs-toast .cs-toast-detail { font-size: 0.82rem; color: var(--cs-muted); margin-top: 0.2rem; line-height: 1.35; }
@keyframes csToastIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }

.cumulous-modal-backdrop {
  position: relative;
  z-index: 20;
  background: transparent;
  display: flex; align-items: center; justify-content: center;
  margin: 0.5rem 0 1rem;
  pointer-events: auto;
  animation: cumulousFadeIn 0.15s ease-out forwards;
}
@keyframes cumulousFadeIn { from { opacity: 0; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .cumulous-modal-backdrop, .cs-toast { animation: none !important; }
}
.cs-window-close {
  position: absolute;
  top: 12px; left: 12px;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: #ff5f57;
  border: 0.5px solid #e0443e;
  cursor: pointer;
  z-index: 5;
  padding: 0;
  font-size: 0;
  line-height: 0;
}
.cs-window-close:hover { background: #ff453a; }
.cs-window-close:hover::after {
  content: "×";
  color: rgba(0,0,0,0.55);
  font-size: 11px;
  font-weight: 700;
  display: flex; align-items: center; justify-content: center; height: 100%;
}
.cs-window-min {
  position: absolute;
  top: 12px; left: 32px;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: #febc2e;
  border: 0.5px solid #dea123;
  cursor: pointer;
  z-index: 5;
  padding: 0;
  font-size: 0;
}
.cs-window-min:hover { background: #ffd60a; }
.success-sheet {
  background: #1c1c1e;
  color: var(--cs-text);
  border: 1px solid var(--cs-line);
  border-radius: 22px;
  padding: 1.5rem 1.5rem 1.35rem;
  min-width: 260px; max-width: 400px;
  width: 100%;
  text-align: center;
  box-shadow: 0 24px 80px rgba(0,0,0,0.55);
  position: relative;
  cursor: default;
  margin: 0 auto;
}
.success-title {
  color: var(--cs-text);
  font-weight: 600;
  font-size: 1.05rem;
  letter-spacing: -0.02em;
  margin-top: 0.65rem;
}
.success-detail {
  color: var(--cs-muted);
  font-size: 0.85rem;
  margin-top: 0.35rem;
  line-height: 1.4;
}
.apple-code-sheet {
  background: #1c1c1e; color: #f5f5f7; border-radius: 22px;
  padding: 1.35rem 1.5rem 1.5rem; min-width: 300px; max-width: 400px;
  text-align: center; box-shadow: 0 24px 80px rgba(0,0,0,0.55);
  position: relative; cursor: default;
  border: 1px solid var(--cs-line);
}
/* Mac traffic-light streamlit buttons */
div[data-testid="column"] button[title="Close window"],
button[title="Close window"],
button[title="Close progress"],
button[aria-label="Close progress"] {
  background: #ff5f57 !important;
  color: transparent !important;
  border: 0.5px solid #e0443e !important;
  border-radius: 50% !important;
  min-height: 14px !important;
  height: 14px !important;
  max-width: 14px !important;
  width: 14px !important;
  min-width: 14px !important;
  padding: 0 !important;
  font-size: 0 !important;
  line-height: 0 !important;
  box-shadow: none !important;
}
button[title="Minimize progress"],
button[aria-label="Minimize progress"] {
  background: #febc2e !important;
  color: transparent !important;
  border: 0.5px solid #dea123 !important;
  border-radius: 50% !important;
  min-height: 14px !important;
  height: 14px !important;
  max-width: 14px !important;
  width: 14px !important;
  min-width: 14px !important;
  padding: 0 !important;
  font-size: 0 !important;
  box-shadow: none !important;
}
button[title="Close window"]:hover,
button[title="Close progress"]:hover { background: #ff453a !important; }
button[title="Minimize progress"]:hover { background: #ffd60a !important; }
/* Click-outside dismiss row */
.cs-backdrop-hit button {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: transparent !important;
  min-height: 2.5rem !important;
  width: 100% !important;
}
/* Compact 3-up Backup | Restore | Device Delete (HIG-ish dense controls) */
button[kind="primary"] {
  min-height: 34px !important;
  padding: 0.4rem 0.55rem !important;
  font-size: 0.8rem !important;
  letter-spacing: -0.01em;
}
/* Custom tab bar — single-line labels */
.cs-tab-bar { margin: 0.35rem 0 0.85rem 0; }
div[data-testid="stHorizontalBlock"] button[kind="secondary"] {
  min-height: 40px !important;
  font-size: 0.88rem !important;
  padding: 0.45rem 0.5rem !important;
  white-space: nowrap !important;
}
/* HIG progress track (Apple-like) */
.cs-progress-track {
  height: 8px !important;
  background: rgba(255,255,255,0.12) !important;
  border-radius: 999px !important;
  overflow: hidden !important;
  border: none !important;
}
.cs-progress-fill {
  background: #007AFF !important;
  box-shadow: 0 0 12px rgba(0,122,255,0.4) !important;
  border-radius: 999px !important;
}
</style>
<script>
/* Scroll + tab position: survive button reruns (Streamlit full script run) */
(function() {
  if (window.__cumulousScrollLock) return;
  window.__cumulousScrollLock = true;
  var KEY = "cumulous_scroll_y";
  function y() { return window.scrollY || document.documentElement.scrollTop || 0; }
  function save() { try { sessionStorage.setItem(KEY, String(y())); } catch (e) {} }
  function restore() {
    try {
      var v = sessionStorage.getItem(KEY);
      if (v === null) return;
      var n = parseInt(v, 10);
      if (!isNaN(n) && n >= 0) window.scrollTo(0, n);
    } catch (e) {}
  }
  window.addEventListener("scroll", save, { passive: true });
  window.addEventListener("beforeunload", save);
  document.addEventListener("click", function(e) {
    var t = e.target;
    if (t && t.closest && t.closest("button")) save();
  }, true);
  function arm() {
    restore();
    setTimeout(restore, 40);
    setTimeout(restore, 160);
    setTimeout(restore, 400);
    setTimeout(restore, 800);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", arm);
  else arm();
  try {
    var root = document.querySelector('[data-testid="stAppViewContainer"]') || document.body;
    new MutationObserver(function() { restore(); }).observe(root, { childList: true, subtree: true });
  } catch (e) {}
})();
(function() {
  if (window.__cumulousModalDismissBound) return;
  window.__cumulousModalDismissBound = true;
  function dismissBackdrop(el) {
    if (!el) return;
    el.style.transition = "opacity 0.15s ease";
    el.style.opacity = "0";
    setTimeout(function() { try { el.remove(); } catch (e) {} }, 160);
  }
  document.addEventListener("click", function(e) {
    var t = e.target;
    if (!t || !t.closest) return;
    if (t.classList.contains("cs-window-close") || t.classList.contains("cs-window-min") || t.classList.contains("apple-esc")) {
      e.preventDefault();
      e.stopPropagation();
      var back = t.closest(".cumulous-modal-backdrop, .cs-progress-backdrop");
      var sheet = t.closest(".success-sheet, .apple-code-sheet, .cs-toast, .cs-dismissable-sheet, .cs-progress-sheet");
      if (back) dismissBackdrop(back);
      else if (sheet) {
        var b2 = sheet.closest(".cumulous-modal-backdrop, .cs-progress-backdrop");
        if (b2) dismissBackdrop(b2);
        else sheet.remove();
      }
      // Also click hidden Streamlit control if present
      var hid = document.querySelector('button[data-testid="baseButton-secondary"][kind], button[title="Minimize progress"], button[title="Close progress"]');
      return;
    }
    if (t.classList.contains("cumulous-modal-backdrop") || t.classList.contains("cs-progress-backdrop")) {
      dismissBackdrop(t);
      var minBtn = document.querySelector('button[title="Minimize progress"]');
      if (minBtn) try { minBtn.click(); } catch (err) {}
    }
  }, true);
})();
</script>
"""
    )
    st_module.markdown(css, unsafe_allow_html=True)



def _close_btn_html() -> str:
    return (
        '<button type="button" class="cs-window-close" aria-label="Close" title="Close"></button>'
    )


def render_flashes(st_module) -> None:
    """Render queued feedback; drop expired toasts; primary sheets stay until dismissed."""
    st = st_module
    if st.session_state.pop("dismiss_all_flashes", False):
        clear_flashes(st)
        return

    flashes = list(st.session_state.get("cumulous_flashes") or [])
    if not flashes:
        return

    now = time.time()
    keep: list[dict] = []
    for i, flash in enumerate(flashes):
        kind = flash.get("kind") or "toast"
        title = html.escape(str(flash.get("title") or "Completed"))
        detail = html.escape(str(flash.get("detail") or ""))
        created = float(flash.get("created_at") or now)
        auto = float(flash.get("auto_dismiss_sec") or 0)
        flash_key = f"{kind}_{i}_{int(created * 1000)}"

        if kind in ("toast", "toast_fail", "info", "success") and flash.get("priority") != "sheet":
            if auto and (now - created) > auto:
                continue
            fail = kind == "toast_fail"
            close = _close_btn_html()
            st.markdown(
                f"""
<div class="cs-toast {'fail' if fail else ''} cs-dismissable-sheet" data-flash-i="{i}">
  {close}
  <div class="cs-toast-title">{title}</div>
  {f'<div class="cs-toast-detail">{detail}</div>' if detail else ''}
</div>
""",
                unsafe_allow_html=True,
            )
            # Reliable Streamlit dismiss (red HTML X is progressive enhancement only)
            d1, d2 = st.columns([1, 8])
            with d1:
                if st.button("×", key=f"toast_x_{flash_key}", help="Close", use_container_width=True):
                    continue
            if not auto or (now - created) <= auto:
                keep.append(flash)
            continue

        if kind in ("sheet", "success") and flash.get("priority") == "sheet":
            # In-flow sheet so Streamlit × / Done remain clickable (no full-screen trap)
            st.markdown(
                f"""
<div class="cumulous-modal-backdrop" role="presentation" id="cumulous-sheet-{i}">
  <div class="success-sheet" role="dialog" aria-labelledby="cs-sheet-title-{i}">
    {GREEN_CHECK_SVG}
    <div class="success-title" id="cs-sheet-title-{i}">{title}</div>
    {f'<div class="success-detail">{detail}</div>' if detail else ''}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
            s1, s2, s3 = st.columns([1, 2, 5])
            with s1:
                if st.button("×", key=f"sheet_x_{flash_key}", help="Close window", use_container_width=True):
                    continue
            with s2:
                if st.button("Done", key=f"sheet_dismiss_{flash_key}", use_container_width=True, type="primary"):
                    continue
            keep.append(flash)
            continue

        if kind in ("apple_code", "confirm_code"):
            # Never show digits — only a quiet banner
            fanout = html.escape(str(flash.get("fanout_summary") or "your Apple devices"))
            st.markdown(
                f"""
<div class="cs-toast cs-dismissable-sheet" role="status" aria-live="polite">
  <div class="cs-toast-title">{title or "Verification"}</div>
  <div class="cs-toast-detail">Code sent to {fanout}. Enter it in the box below — it won’t appear here.</div>
</div>
""",
                unsafe_allow_html=True,
            )
            c_x, _ = st.columns([1, 8])
            with c_x:
                if st.button("×", key=f"code_x_{flash_key}", help="Close window", use_container_width=True):
                    continue
            if flash.get("sticky"):
                keep.append(flash)
            continue

        st.markdown(
            f"""
<div class="cs-toast">
  {_close_btn_html()}
  <div class="cs-toast-title">{title}</div>
  {f'<div class="cs-toast-detail">{detail}</div>' if detail else ''}
</div>
""",
            unsafe_allow_html=True,
        )
        d_fb, _ = st.columns([1, 8])
        with d_fb:
            if st.button("×", key=f"fb_x_{flash_key}", help="Close", use_container_width=True):
                continue
        keep.append(flash)

    st.session_state["cumulous_flashes"] = keep

    if keep and any(f.get("auto_dismiss_sec") for f in keep):
        try:
            from streamlit_autorefresh import st_autorefresh

            st_autorefresh(interval=900, key="cumulous_toast_tick", limit=8)
        except Exception:
            pass


def push_macos_native_code(code: str, title: str = "Confirm 4-Digit Code") -> bool:
    """One Notification Center banner only (no extra dialog windows)."""
    digits = "".join(c for c in str(code) if c.isdigit())[:4].zfill(4)
    spaced = f"{digits[0]}  {digits[1]}  {digits[2]}  {digits[3]}"
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "Code {spaced} — also on your iPhone · enter in Cumulous" '
                f'with title "{title}" sound name "Glass"',
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


def push_macos_success(message: str) -> None:
    try:
        safe = message.replace('"', "'")[:120]
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{safe}" with title "Cumulous" sound name "Glass"',
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def render_action_badge(st_module, action_id: str) -> None:
    from cumulous.action_status import get_status
    from cumulous.ux_copy import badge_ui, friendly_message, is_technical_noise

    rec = get_status(action_id)
    status = rec.get("status") or "idle"
    if status == "idle" and not rec.get("message"):
        return
    label, color = badge_ui(status)
    msg = friendly_message(str(rec.get("message") or label or ""), fallback="", allow_empty=True)
    if not msg:
        msg = label
    detail_raw = str(rec.get("detail") or "")
    detail = ""
    if detail_raw and not is_technical_noise(detail_raw):
        detail = friendly_message(detail_raw, fallback="", allow_empty=True)
    if not msg and not label:
        return
    st_module.markdown(
        f"<div class='action-row'>"
        f"<span class='cs-badge' style='background:{color}18;color:{color};border:1px solid {color}40'>"
        f"{html.escape(label or 'Status')}</span>"
        f"<span class='cs-muted'>{html.escape(msg)}"
        f"{(' · ' + html.escape(detail)) if detail and detail != msg else ''}</span></div>",
        unsafe_allow_html=True,
    )
