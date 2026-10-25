"""CEO-facing copy must never surface terminal dumps."""

from __future__ import annotations

from cumulous.ux_copy import (
    badge_ui,
    client_error,
    friendly_message,
    is_technical_noise,
    progress_headline,
    public_repair,
    public_verification,
)


def test_noise_detection():
    assert is_technical_noise("Traceback (most recent call last):")
    assert is_technical_noise("ErrorCode 208")
    assert is_technical_noise("a" * 50)  # long token
    assert not is_technical_noise("Unlock the iPhone once when prompted")


def test_friendly_passcode_and_pair():
    assert "Unlock" in friendly_message("ErrorCode 208: Device locked")
    assert "Trust" in friendly_message("pair failed — Trust this computer")
    assert "Connect" in friendly_message("no device found")


def test_client_error_status_gates():
    assert client_error("anything", status="running") is None
    assert client_error("anything", status="complete") is None
    assert client_error(None, status="waiting_passcode") is None
    msg = client_error("MBErrorDomain/208", status="needs_resume")
    assert msg and "Unlock" in msg
    assert "208" not in msg
    assert "Traceback" not in (client_error("Traceback: x", status="error") or "")


def test_progress_headline_not_complete_mid_run():
    assert progress_headline(14, status="running") == "Backup"
    assert progress_headline(100, status="complete") == "Backup complete"
    assert "Complete" not in progress_headline(50, status="waiting_passcode")


def test_badge_soft_error_color():
    label, color = badge_ui("error")
    assert label == "Needs a moment"
    assert color == "#ffd60a"  # amber, not terminal red


def test_public_verification_no_paths():
    v = public_verification(
        {
            "ok_samples": 3,
            "fail_samples": 0,
            "last_samples": ["/Volumes/secret/path"],
        }
    )
    assert v == {"ok": True, "checked": True}
    assert "path" not in str(v).lower() or "last" not in v
    assert public_repair({"ok": True, "actions": ["x"], "device_dir": "/secret"}) == {"ok": True}
