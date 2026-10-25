"""py2app setup for standalone Cumulous Mac .app (not browser-only).

Build:
  cd ~/DelphiHomeController
  .venv/bin/python setup_py2app.py py2app

Produces dist/Cumulous.app — double-click launches splash + Streamlit shell
via cumulous.launcher (local loopback only).

Industry note (2025–2026): shipping a polished Mac app still uses AppKit
window chrome (traffic lights), Dock icon, and .app bundle; py2app packages
Python backends for private/self-hosted tools. App Store listing requires
sandboxing / notarization beyond this private build path.
"""

from __future__ import annotations

from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent
ICON = ROOT / "cumulous" / "assets" / "icons" / "Cumulous.icns"

APP = ["cumulous/launcher.py"]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": str(ICON) if ICON.exists() else None,
    "plist": {
        "CFBundleName": "Cumulous",
        "CFBundleDisplayName": "Cumulous Cloud",
        "CFBundleIdentifier": "com.delphitech.cumulous",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    },
    "packages": ["cumulous", "streamlit", "fastapi", "uvicorn"],
    "includes": ["cumulous.app", "cumulous.launcher", "cumulous.fastapi_bridge"],
}

setup(
    name="Cumulous",
    app=APP,
    options={"py2app": {k: v for k, v in OPTIONS.items() if v is not None}},
    setup_requires=["py2app"],
)
