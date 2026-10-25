"""Backup ops: identity snapshot encrypt + restore to Mac."""

from __future__ import annotations

from cumulous.backup_ops import list_device_backup_status, restore_to_mac, secure_backup_device
from cumulous.progressive_backup import current_head


def test_secure_backup_without_idevice(cumulous_home, monkeypatch):
    monkeypatch.setenv("CUMULOUS_VAULT_PASSWORD", "VaultTest1!")
    # no phone tools required — identity snapshot still seals
    res = secure_backup_device(
        "test-device-1",
        password="VaultTest1!",
        apple_account_id="t@example.test",
        display_name="Test Phone",
        run_full_idevice=False,
        action_id="test_bak",
    )
    assert res.get("ok") is True
    assert current_head("test-device-1")
    st = list_device_backup_status("test-device-1")
    assert st["backed_up"] is True

    head = current_head("test-device-1")
    out = restore_to_mac("test-device-1", head, password="VaultTest1!", action_id="test_restore")
    assert out.get("ok") is True
    assert out.get("file_count", 0) >= 1
