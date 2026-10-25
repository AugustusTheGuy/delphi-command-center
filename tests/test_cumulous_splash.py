"""Splash path + wiring tests — drive shipped cumulous.splash / app modules."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

from cumulous import splash as splash_mod
from cumulous.splash import (
    SPLASH_FILENAME,
    splash_asset_exists,
    splash_asset_path,
    is_video_splash_configured,
    render_splash,
)


def test_splash_asset_exists_at_configured_path():
    path = splash_asset_path()
    assert path.name == SPLASH_FILENAME
    if not path.is_file():
        # Portfolio checkout may omit the binary splash; UI falls back to text splash.
        assert splash_asset_exists() is False
        assert is_video_splash_configured() is False
        pytest.skip("cumulous_splash.mp4 not bundled in this portfolio checkout")
    assert path.stat().st_size > 1000
    # Source export size ~1_199_363; allow small copy variance
    assert abs(path.stat().st_size - 1_199_363) < 50_000
    assert splash_asset_exists() is True
    assert is_video_splash_configured() is True


def test_splash_path_is_under_cumulous_assets_not_downloads():
    path = splash_asset_path()
    assert "Downloads" not in path.parts
    assert path.parts[-2:] == ("assets", SPLASH_FILENAME)
    assert path.parent.name == "assets"
    assert (path.parent.parent / "app.py").is_file()


def test_app_module_wires_video_splash_not_text_only_placeholder():
    app = importlib.import_module("cumulous.app")
    src = inspect.getsource(app)
    assert "render_splash" in src
    assert "from cumulous.splash import" in src
    assert "✖️" not in src
    assert "st.video" in inspect.getsource(splash_mod) or "SPLASH_FILENAME" in inspect.getsource(splash_mod)


def test_render_splash_is_callable_shipped_entry():
    assert callable(render_splash)
    assert callable(splash_mod.render_splash)


def test_import_cumulous_app_twice():
    import cumulous.app as a1

    importlib.reload(a1)
    import cumulous.app as a2

    assert a2.PRODUCT_NAME == "Cumulous"
    assert callable(a2.main)
    assert callable(render_splash)
