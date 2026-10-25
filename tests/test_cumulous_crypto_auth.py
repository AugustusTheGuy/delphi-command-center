"""Real crypto, TOTP, lockout tests against shipped Cumulous modules."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from cumulous.crypto_vault import open_bytes, seal_bytes
from cumulous.lockout import (
    FAIL_THRESHOLD,
    FIRST_LOCK_SEC,
    is_locked,
    record_failure,
    record_success,
)
from cumulous.totp_2fa import current_code, enroll, load_secret, verify_totp


def test_seal_open_round_trip(cumulous_home):
    pw = "TestVault9!"
    plain = b"hello-cumulous-secret-payload"
    blob = seal_bytes(plain, pw)
    assert blob != plain
    assert open_bytes(blob, pw) == plain


def test_wrong_password_fails(cumulous_home):
    blob = seal_bytes(b"data", "GoodPass1!")
    with pytest.raises((InvalidTag, ValueError, Exception)):
        open_bytes(blob, "WrongPass1!")


def test_totp_enroll_verify_reject(cumulous_home):
    info = enroll(account_name="testuser")
    secret = info["secret"]
    assert secret
    assert load_secret() == secret
    assert "otpauth://" in info["otpauth_uri"]
    code = current_code(secret)
    assert verify_totp(secret, code) is True
    assert verify_totp(secret, "000000") is False
    assert verify_totp(secret, "bad") is False


def test_lockout_after_ten_failures_with_injected_now(cumulous_home):
    t0 = 1_700_000_000.0
    for i in range(FAIL_THRESHOLD - 1):
        r = record_failure(now=t0 + i)
        assert r["locked"] is False
        assert r["fail_count_window"] == i + 1
    r = record_failure(now=t0 + FAIL_THRESHOLD)
    assert r["locked"] is True
    assert r.get("lock_kind") == "1h"
    assert r["seconds_remaining"] == pytest.approx(FIRST_LOCK_SEC, abs=1)
    locked, rem = is_locked(now=t0 + FAIL_THRESHOLD + 10)
    assert locked is True
    assert rem > 0
    # still locked before expiry
    locked2, _ = is_locked(now=t0 + FAIL_THRESHOLD + FIRST_LOCK_SEC - 1)
    assert locked2 is True
    # unlocked after 1h
    locked3, rem3 = is_locked(now=t0 + FAIL_THRESHOLD + FIRST_LOCK_SEC + 1)
    assert locked3 is False
    assert rem3 == 0.0
    record_success(now=t0 + FAIL_THRESHOLD + FIRST_LOCK_SEC + 2)
