"""Apple Account model, 2xsecrets, catalog, confirm fan-out."""

from __future__ import annotations

from cumulous.apple_accounts import (
    attach_device_to_account,
    catalog_by_apple_account,
    ensure_account,
    ensure_account_2fa,
    get_account_2fa_secret,
    read_2xsecrets_for_ceo,
    verify_account_2fa,
)
from cumulous.challenge_codes import spawn_challenge_for_apple_account, verify_challenge
from cumulous.devices import register_device
from cumulous.progressive_backup import create_generation
from cumulous.totp_2fa import current_code


def test_ensure_account_and_2fa_per_apple_id(cumulous_home):
    ensure_account("owner@example.test", display_name="Owner", verified=True)
    info = ensure_account_2fa("owner@example.test")
    assert info["totp_secret"]
    secret = get_account_2fa_secret("owner@example.test")
    assert secret == info["totp_secret"]
    # second call does not rotate
    info2 = ensure_account_2fa("owner@example.test")
    assert info2["totp_secret"] == secret
    assert info2["created"] is False
    assert verify_account_2fa("owner@example.test", current_code(secret)) is True
    assert verify_account_2fa("owner@example.test", "000000") is False
    x2 = read_2xsecrets_for_ceo()
    assert "owner@example.test" in x2["accounts"]


def test_catalog_groups_devices_under_account(cumulous_home):
    ensure_account("family@example.test", verified=True)
    register_device(
        "dev-a",
        display_name="Phone A",
        owner_username="family@example.test",
        apple_account_id="family@example.test",
    )
    attach_device_to_account("family@example.test", "dev-a")
    create_generation("dev-a", {"a.txt": b"hello"}, "pw-Test1!", mode="persistent")
    cat = catalog_by_apple_account()
    # may include scraped accounts empty; find ours
    match = [c for c in cat if c.get("apple_id") == "family@example.test"]
    assert match
    devs = match[0]["devices"]
    assert any(d["device_id"] == "dev-a" and d["backed_up"] for d in devs)


def test_spawn_for_apple_account_unions_ceo(cumulous_home):
    ensure_account("user@example.test")
    register_device(
        "u1",
        display_name="U1",
        apple_account_id="user@example.test",
        owner_username="user@example.test",
    )
    register_device(
        "ceo1",
        display_name="CEO1",
        apple_account_id="ceo@example.test",
        owner_username="ceo@example.test",
        is_ceo_override=True,
    )
    attach_device_to_account("user@example.test", "u1")
    ch = spawn_challenge_for_apple_account(
        purpose="confirm_user",
        apple_account_id="user@example.test",
    )
    assert ch["code"].isdigit() and len(ch["code"]) == 4
    assert "u1" in ch["fanout_device_ids"]
    assert "ceo1" in ch["fanout_device_ids"]
    assert verify_challenge(ch["code"], purpose="confirm_user") is True
