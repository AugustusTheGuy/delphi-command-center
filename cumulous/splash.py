"""Delphi Technologies splash — full-screen iOS; medium borderless centered Mac."""

from __future__ import annotations

import time
from pathlib import Path

SPLASH_FILENAME = "cumulous_splash.mp4"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
SPLASH_PATH = ASSETS_DIR / SPLASH_FILENAME
ICON_PATH = ASSETS_DIR / "icons" / "cumulous_mac_icon.png"
IOS_ICON = ASSETS_DIR / "icons" / "cumulous_ios_icon.png"
APPICON = ASSETS_DIR / "icons" / "AppIcon-1024.png"
DEFAULT_DURATION = 2.4
ORG_TITLE = "Delphi Technologies"
PRODUCT_SUB = "Cumulous"


def splash_asset_path() -> Path:
    return SPLASH_PATH


def splash_asset_exists() -> bool:
    p = splash_asset_path()
    return p.is_file() and p.stat().st_size > 1000


def is_video_splash_configured() -> bool:
    return splash_asset_exists() and SPLASH_FILENAME in str(splash_asset_path())


def probe_duration_sec(path: Path) -> float:
    import json
    import shutil
    import subprocess

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return DEFAULT_DURATION
    try:
        out = subprocess.check_output(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            timeout=5,
        )
        data = json.loads(out.decode())
        dur = float(data.get("format", {}).get("duration") or DEFAULT_DURATION)
        return max(1.0, min(dur + 0.05, 8.0))
    except Exception:
        return DEFAULT_DURATION


def projected_duration_sec() -> float:
    try:
        from cumulous.app_update import projected_splash_duration_sec

        return projected_splash_duration_sec()
    except Exception:
        return DEFAULT_DURATION


def render_splash(st_module) -> bool:
    """Mac: medium borderless centered Delphi Technologies splash, then app."""
    st = st_module
    if st.session_state.get("splash_done"):
        return True

    # Always-latest version/icon sync on every load
    try:
        from cumulous.app_update import on_app_launch

        st.session_state["cumulous_launch_meta"] = on_app_launch()
    except Exception:
        st.session_state["cumulous_launch_meta"] = {}

    duration = projected_duration_sec()
    # Scale stage size with load time: longer load → slightly larger brand stage
    # Medium box: ~min(38vw, 320–400px) depending on duration
    stage_px = int(min(400, max(280, 240 + duration * 40)))

    icon = ICON_PATH if ICON_PATH.is_file() else (APPICON if APPICON.is_file() else None)
    ver = "0.2.0"
    try:
        from cumulous.app_update import package_version

        ver = package_version()
    except Exception:
        pass

    st.markdown(
        f"""
<style>
header, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
#MainMenu, [data-testid="stHeader"], [data-testid="stStatusWidget"] {{
  visibility: hidden !important; height: 0 !important;
}}
.stApp, .stApp > header, .block-container {{
  background: #000000 !important;
  padding: 0 !important;
  margin: 0 !important;
  max-width: 100% !important;
}}
div[data-testid="stVerticalBlock"] {{ gap: 0 !important; }}
.cumulous-splash-wrap {{
  position: fixed; inset: 0; z-index: 99998;
  background: #000;
  display: flex; align-items: center; justify-content: center;
  animation: splashFade 0.35s ease-out;
}}
@keyframes splashFade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
/* Medium-sized borderless centered box (Mac) */
.cumulous-splash-stage {{
  width: min(42vw, {stage_px}px);
  max-width: {stage_px}px;
  border: none !important; outline: none !important;
  box-shadow: none !important;
  background: transparent !important;
  overflow: hidden;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 1.1rem;
  padding: 1.5rem;
}}
.cumulous-splash-icon {{
  width: min(28vw, {int(stage_px * 0.55)}px); height: min(28vw, {int(stage_px * 0.55)}px);
  aspect-ratio: 1 / 1;
  border-radius: 22.5%;
  overflow: hidden;
  animation: iconPulse 2.2s ease-in-out infinite;
}}
.cumulous-splash-icon img {{
  width: 100%; height: 100%; object-fit: cover; border: none !important;
}}
.cumulous-splash-title {{
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
  font-size: clamp(1.15rem, 2.4vw, 1.55rem);
  font-weight: 600; letter-spacing: -0.02em; color: #f5f5f7;
  text-align: center;
}}
.cumulous-splash-sub {{
  font-size: 0.92rem; color: #8e8e93; letter-spacing: 0.04em;
  text-align: center;
}}
.cumulous-splash-ver {{
  font-size: 0.72rem; color: #636366; margin-top: 0.25rem;
}}
@keyframes iconPulse {{
  0%, 100% {{ transform: scale(1); opacity: 1; }}
  50% {{ transform: scale(1.03); opacity: 0.96; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )

    import base64

    if icon and icon.is_file():
        b64 = base64.b64encode(icon.read_bytes()).decode("ascii")
        st.markdown(
            f"""
<div class="cumulous-splash-wrap">
  <div class="cumulous-splash-stage">
    <div class="cumulous-splash-icon">
      <img src="data:image/png;base64,{b64}" alt="Cumulous" />
    </div>
    <div class="cumulous-splash-title">{ORG_TITLE}</div>
    <div class="cumulous-splash-sub">{PRODUCT_SUB}</div>
    <div class="cumulous-splash-ver">v{ver}</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
    elif splash_asset_exists():
        st.video(str(splash_asset_path()), start_time=0)
        duration = min(probe_duration_sec(splash_asset_path()), duration + 0.5)
    else:
        st.session_state.splash_done = True
        st.rerun()
        return True

    time.sleep(duration)
    st.session_state.splash_done = True
    st.rerun()
    return False
