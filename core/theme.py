"""Brand theme. Black and silver, with money green only on the main action."""

import json
import re
from pathlib import Path

PRIMARY = "#C5CCD6"
SECONDARY = "#22C55E"
TERTIARY_LIGHT = "#F4F5F7"
TERTIARY_DARK = "#070809"
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
        "tertiary_color": sanitize_color(tertiary, TERTIARY_DARK),
    }, indent=2))


THEMES = {
    "dark": {
        "bg": "#070809",
        "text": "#E8EAED",
        "muted": "#9AA3AD",
        "card": "#121417",
        "line": "#3A414A",
        "sidebar": "#0A0C0E",
    },
    "light": {
        "bg": "#F4F5F7",
        "text": "#121417",
        "muted": "#5C6570",
        "card": "#FFFFFF",
        "line": "#C5CCD6",
        "sidebar": "#FFFFFF",
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

html, body, [class*="css"] {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
}}

.stApp {{
    background: {t["bg"]};
    color: {t["text"]};
}}

[data-testid="stToolbar"], #MainMenu, footer {{
    visibility: hidden;
    height: 0;
}}
header[data-testid="stHeader"] {{
    background: transparent;
}}

section[data-testid="stSidebar"] {{
    background: {t["sidebar"]};
    border-right: 1px solid {t["line"]};
}}
section[data-testid="stSidebar"] [data-testid="stMarkdown"] {{
    color: {t["text"]};
}}

.dhc-header {{
    margin-bottom: 1.25rem;
    border-bottom: 1px solid {t["line"]};
    padding-bottom: 0.75rem;
}}
.dhc-kicker {{
    color: {t["muted"]};
    font-size: 0.8rem;
    margin: 0;
}}
.dhc-title {{
    font-size: 1.75rem;
    font-weight: 600;
    color: {t["text"]};
    margin: 0.1rem 0 0;
    letter-spacing: -0.02em;
}}
.dhc-subtitle {{
    color: {t["muted"]};
    font-size: 0.95rem;
    margin: 0.15rem 0 0;
}}
a {{ color: {t["text"]}; }}

.stTextInput input, .stTextArea textarea {{
    background: {t["card"]};
    color: {t["text"]};
    border-color: {t["line"]};
}}
.stTextInput input:focus, .stTextArea textarea:focus {{
    outline: 2px solid var(--dhc-primary);
    border-color: var(--dhc-primary);
}}

h1, h2, h3, .stMarkdown p {{
    color: {t["text"]};
}}

.stButton > button {{
    background: transparent;
    color: {t["text"]};
    border: 1px solid var(--dhc-primary);
    border-radius: 8px;
    font-weight: 600;
}}
.stButton > button:hover {{
    border-color: {t["text"]};
    color: {t["text"]};
}}
.stButton > button[kind="primary"] {{
    background: var(--dhc-secondary);
    color: #04140A;
    border-color: var(--dhc-secondary);
}}
div[class*="st-key-home_"] button {{
    min-height: 72px;
    font-size: 1.35rem;
}}

.dhc-card {{
    background: {t["card"]};
    border: 1px solid {t["line"]};
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
}}
.dhc-choice {{
    color: {t["muted"]};
    font-size: 0.9rem;
    margin: 0.25rem 0 0.8rem;
}}
.dhc-setup {{
    margin: 0.15rem 0;
    color: {t["text"]};
}}
.dhc-status-ok {{ color: #22C55E; font-weight: 600; }}
.dhc-status-idle {{ color: {t["muted"]}; }}
.dhc-status-err {{ color: #F87171; }}
</style>
"""


THEME_CSS = get_theme_css("dark")
