"""Brand theme — dark default, optional day mode, three user colors."""

import json
import re
from pathlib import Path

PRIMARY = "#6A0DAD"
SECONDARY = "#FF6600"
GOLD = "#D4AF37"
TERTIARY_LIGHT = "#F4F0FA"
TERTIARY_DARK = "#1A1428"
APPEARANCE_FILE = Path(__file__).resolve().parent.parent / "data" / "appearance.json"


def sanitize_color(value: str, fallback: str) -> str:
    if isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value
    return fallback


def palette_for(profile: dict | None) -> dict:
    source: dict = profile or {}
    if not profile and APPEARANCE_FILE.exists():
        try:
            loaded = json.loads(APPEARANCE_FILE.read_text())
            if isinstance(loaded, dict):
                source = loaded
        except (OSError, json.JSONDecodeError):
            source = {}
    return {
        "primary": source.get("primary_color") or source.get("primary") or "",
        "secondary": source.get("secondary_color") or source.get("secondary") or "",
        "tertiary": source.get("tertiary_color") or source.get("tertiary") or "",
    }


def save_appearance(primary: str, secondary: str, tertiary: str) -> None:
    APPEARANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    APPEARANCE_FILE.write_text(json.dumps({
        "primary_color": sanitize_color(primary, PRIMARY),
        "secondary_color": sanitize_color(secondary, SECONDARY),
        "tertiary_color": sanitize_color(tertiary, TERTIARY_LIGHT),
    }, indent=2))

THEMES = {
    "dark": {
        "bg": "linear-gradient(180deg, #0a0612 0%, #14101f 100%)",
        "text": "#e8e0f5",
        "muted": "#9b8fb8",
        "card": "#1a1428",
        "card_border": "#2d2440",
        "splash_bg": "#0a0612",
    },
    "light": {
        "bg": "linear-gradient(180deg, #ffffff 0%, #faf8ff 100%)",
        "text": PRIMARY,
        "muted": "#666666",
        "card": "#ffffff",
        "card_border": "#ece6f5",
        "splash_bg": "#0a0612",
    },
}


def get_theme_css(mode: str = "dark", palette: dict | None = None) -> str:
    t = THEMES.get(mode, THEMES["dark"])
    colors = palette or {}
    tertiary_fallback = TERTIARY_LIGHT if mode == "light" else TERTIARY_DARK
    primary = sanitize_color(str(colors.get("primary") or ""), PRIMARY)
    secondary = sanitize_color(str(colors.get("secondary") or ""), SECONDARY)
    tertiary = sanitize_color(str(colors.get("tertiary") or ""), tertiary_fallback)
    return f"""
<style>
:root {{
    --dhc-primary: {primary};
    --dhc-secondary: {secondary};
    --dhc-tertiary: {tertiary};
}}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}}

.stApp {{
    background: {t["bg"]};
    color: {t["text"]};
}}

.dhc-header {{
    display: flex; align-items: center; gap: 12px; margin-bottom: 0.5rem;
    border-bottom: 3px solid var(--dhc-tertiary); padding-bottom: 0.35rem;
}}
.dhc-title {{ font-size: 1.75rem; font-weight: 700; color: var(--dhc-primary); margin: 0; }}
a {{ color: var(--dhc-primary); }}
.stTextInput input:focus, .stTextArea textarea:focus {{
    outline: 2px solid var(--dhc-primary);
    border-color: var(--dhc-primary);
}}
.dhc-gold {{ color: {GOLD}; font-weight: 700; letter-spacing: 0.04em; }}
.dhc-subtitle {{ color: {t["muted"]}; font-size: 0.9rem; margin-top: 0; }}

.stTabs [data-baseweb="tab"] {{ color: {t["text"]}; font-weight: 600; }}
.stTabs [aria-selected="true"] {{
    color: var(--dhc-secondary) !important;
    border-bottom-color: var(--dhc-secondary) !important;
}}

.stButton > button {{
    background: var(--dhc-secondary);
    color: white;
    border: none;
    border-radius: 10px;
    padding: 0.5rem 1.25rem;
    font-weight: 600;
}}
.stButton > button:hover {{ filter: brightness(1.08); color: white; }}

.dhc-card {{
    background: color-mix(in srgb, var(--dhc-tertiary) 14%, {t["card"]});
    border: 1px solid var(--dhc-primary);
    border-radius: 14px;
    padding: 1rem 1.25rem;
    box-shadow: 0 2px 12px color-mix(in srgb, var(--dhc-primary) 18%, transparent);
    margin-bottom: 1rem;
}}

.dhc-status-ok {{ color: #16a34a; }}
.dhc-status-warn {{ color: {SECONDARY}; }}
.dhc-status-err {{ color: #dc2626; }}

.dhc-splash-wrap {{
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: {t["splash_bg"]};
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}}

.dhc-splash-brand {{
    font-size: 2rem;
    color: {GOLD};
    margin-bottom: 2rem;
    font-weight: 700;
}}

.dhc-quadrant-grid {{
    width: 200px;
    height: 200px;
    position: relative;
    border: 3px solid var(--dhc-primary);
}}

.dhc-q-line-h, .dhc-q-line-v {{ position: absolute; background: var(--dhc-primary); }}
.dhc-q-line-h {{ left: 0; right: 0; top: 50%; height: 3px; transform: translateY(-50%); }}
.dhc-q-line-v {{ top: 0; bottom: 0; left: 50%; width: 3px; transform: translateX(-50%); }}

.dhc-q-symbol {{
    position: absolute;
    font-size: 2.5rem;
    font-weight: 700;
    width: 50%;
    height: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    animation: dhc-paint 0.5s ease forwards;
}}

.dhc-q-tl {{ top: 0; left: 0; color: var(--dhc-primary); animation-delay: 0.6s; }}
.dhc-q-tr {{ top: 0; right: 0; color: var(--dhc-secondary); animation-delay: 1.1s; }}
.dhc-q-bl {{ bottom: 0; left: 0; color: var(--dhc-primary); animation-delay: 1.6s; }}
.dhc-q-br {{ bottom: 0; right: 0; color: {GOLD}; animation-delay: 2.1s; }}

.dhc-q-cross {{
    opacity: 0;
    animation: dhc-paint 0.5s ease forwards;
    animation-delay: 0.1s;
}}

@keyframes dhc-paint {{
    from {{ opacity: 0; transform: scale(0.6); }}
    to {{ opacity: 1; transform: scale(1); }}
}}
</style>
"""

# Back-compat
THEME_CSS = get_theme_css("dark")