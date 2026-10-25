"""Cumulous design tokens — matte black · thin metallic silver · Apple blue / deny red.

Use these tokens for Mac (CSS vars), iOS (CumulousTheme), PWA, and future UI so
every surface stays consistent. Do not reintroduce gold or multi-hue accents.
"""

from __future__ import annotations

# —— Surfaces ——
BG_MATTE = "#050505"
ELEVATED = "#0a0a0a"
CARD = "#0e0e0e"
CARD_GLASS = "rgba(14,14,16,0.96)"

# —— Thin metallic silver (lines / hairlines) ——
LINE = "rgba(200, 202, 210, 0.22)"
LINE_STRONG = "rgba(232, 234, 242, 0.42)"
SILVER = "#c8cad2"
SILVER_SOFT = "rgba(200, 202, 210, 0.12)"

# —— Text: silver that glows toward bright white ——
TEXT = "#ffffff"
TEXT_SHINE = "#fafafa"
MUTED = "#c7c7cc"
FAINT = "#8e8e93"

# —— Semantic buttons (Apple HIG) ——
# All Cumulous action buttons use Apple systemBlue (including former deny/red actions)
APPLE_BLUE = "#007AFF"
APPLE_BLUE_PRESS = "#0066d6"
# Status / traffic-light chrome only (not action buttons)
APPLE_RED = "#FF3B30"
APPLE_RED_DARK = "#FF453A"  # dark-mode friendly systemRed
# Apple HIG traffic-light green for affirmed status text (not action buttons)
APPLE_GREEN = "#34C759"
APPLE_GREEN_BRIGHT = "#30D158"  # dark-mode systemGreen
# macOS window traffic lights (true Mac chrome — not product action buttons)
TRAFFIC_CLOSE = "#ff5f57"
TRAFFIC_MINIMIZE = "#febc2e"
TRAFFIC_ZOOM = "#28c840"

# Legacy aliases — action fills use Apple blue everywhere
SUCCESS = APPLE_BLUE  # progress fill uses blue accent now
DANGER = APPLE_BLUE  # former deny-red buttons now Apple blue

# —— Progress ——
PROGRESS_TRACK = "rgba(255,255,255,0.08)"
PROGRESS_FILL_START = "#0A84FF"
PROGRESS_FILL_END = "#007AFF"

RADIUS = "18px"
RADIUS_SM = "12px"


def css_root_variables() -> str:
    """CSS custom properties for Streamlit / PWA shells."""
    return f"""
:root {{
  --cs-bg: {BG_MATTE};
  --cs-elevated: {ELEVATED};
  --cs-card: {CARD_GLASS};
  --cs-card-solid: {CARD};
  --cs-line: {LINE};
  --cs-line-strong: {LINE_STRONG};
  --cs-silver: {SILVER};
  --cs-silver-soft: {SILVER_SOFT};
  --cs-text: {TEXT};
  --cs-text-shine: {TEXT_SHINE};
  --cs-muted: {MUTED};
  --cs-faint: {FAINT};
  --cs-blue: {APPLE_BLUE};
  --cs-blue-press: {APPLE_BLUE_PRESS};
  --cs-red: {APPLE_RED};
  --cs-red-dark: {APPLE_RED_DARK};
  --cs-green: {APPLE_GREEN};
  --cs-green-bright: {APPLE_GREEN_BRIGHT};
  --cs-progress-a: {PROGRESS_FILL_START};
  --cs-progress-b: {PROGRESS_FILL_END};
  --cs-radius: {RADIUS};
  --cs-radius-sm: {RADIUS_SM};
  /* deprecated aliases → silver/blue (do not use gold) */
  --cs-gold: {SILVER};
  --cs-gold-soft: {SILVER_SOFT};
  --cs-sky: {APPLE_BLUE};
  --cs-amber: #ffd60a;
}}
"""
