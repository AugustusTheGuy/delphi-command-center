"""Isolate Cumulous secrets/vault under a temp CUMULOUS_HOME for every test."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def cumulous_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "cumulous_home"
    home.mkdir()
    monkeypatch.setenv("CUMULOUS_HOME", str(home))
    monkeypatch.setenv("CUMULOUS_FORCE_INTERNAL_VAULT", "1")
    return home
