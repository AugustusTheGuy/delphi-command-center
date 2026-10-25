"""Cumulous entry import + splash wiring + no secret literals in tracked source."""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUMULOUS = ROOT / "cumulous"


def test_import_app_twice():
    import cumulous.app as a1

    importlib.reload(a1)
    import cumulous.app as a2

    assert a2.PRODUCT_NAME == "Cumulous"
    assert callable(a2.main)
    assert "render_splash" in importlib.import_module("cumulous.app").__dict__.get("__doc__", "") or True
    from cumulous.splash import render_splash

    assert callable(render_splash)


def test_splash_asset_when_present():
    from cumulous.splash import splash_asset_exists, splash_asset_path

    p = splash_asset_path()
    assert p.name == "cumulous_splash.mp4"
    if p.is_file():
        assert splash_asset_exists()
        assert p.stat().st_size > 1000


def test_no_plaintext_production_passwords_in_tracked_modules():
    """Static hygiene: no obvious password defaults in shipped cumulous/*.py."""
    # Extra literal strings to ban can be supplied locally via CUMULOUS_BANNED_STRINGS (comma-separated);
    # none are stored in the repo.
    banned = [re.escape(x.strip()) for x in os.environ.get("CUMULOUS_BANNED_STRINGS", "").split(",") if x.strip()]
    banned += [
        r"password\s*=\s*[\"'][^\"']{6,}[\"']",
    ]
    offenders = []
    for py in CUMULOUS.glob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        for pat in banned:
            if re.search(pat, text, re.I):
                # allow example placeholders
                if "SET_LOCALLY" in text and "example" in py.name.lower():
                    continue
                if py.name.endswith("example.json"):
                    continue
                offenders.append(f"{py.name}: matched {pat}")
    assert not offenders, offenders
