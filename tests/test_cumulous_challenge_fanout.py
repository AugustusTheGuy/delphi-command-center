"""Challenge 4-digit fan-out union + verify/reject on shipped modules."""

from __future__ import annotations

import inspect

from cumulous import app as app_mod
from cumulous.challenge_codes import (
    TTL_SEC,
    fanout_targets,
    spawn_challenge_for_user,
    verify_challenge,
)
from cumulous.devices import ceo_override_device_ids, devices_for_user, register_device


def test_streamlit_app_uses_registry_spawn_not_empty_user_list():
    """Mac UI must call registry spawn helpers (union), not hardcode []."""
    src = inspect.getsource(app_mod)
    assert "spawn_challenge_for_user" in src or "spawn_challenge_for_apple_account" in src
    assert "user_device_ids=[]" not in src
    assert "Generate Code" in src or "generate" in src.lower()
    assert "Confirm User" in src
    assert "2xsecrets" in src


def test_wrong_and_expired_code_fail(cumulous_home):
    register_device("d1", display_name="D1", owner_username="bob", is_ceo_override=False)
    register_device("d2", display_name="D2", owner_username="BEARACCOUNT", is_ceo_override=True)
    ch = spawn_challenge_for_user(
        purpose="setup",
        requesting_user_id="bob",
        now=1_000_000.0,
    )
    assert set(ch["fanout_device_ids"]) == {"d1", "d2"}
    assert verify_challenge("9999", purpose="setup", now=1_000_000.0) is False
    assert verify_challenge(ch["code"], purpose="setup", now=1_000_000.0 + TTL_SEC + 1) is False


def test_spawn_without_devices_still_returns_onscreen_code(cumulous_home):
    ch = spawn_challenge_for_user(
        purpose="setup",
        requesting_user_id="solo",
    )
    assert ch["code"].isdigit() and len(ch["code"]) == 4
    assert ch["fanout_device_ids"] == []
    assert verify_challenge(ch["code"], purpose="setup") is True
