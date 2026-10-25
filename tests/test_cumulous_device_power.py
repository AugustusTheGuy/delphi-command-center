"""Wake policy: snapshot prior Auto-Lock and restore on any end."""

from __future__ import annotations

from cumulous.device_power import (
    begin_backup_wake_policy,
    end_backup_wake_policy,
    power_policy_for_clients,
    record_client_auto_lock_snapshot,
)


def test_snapshot_and_restore_flow(cumulous_home):
    record_client_auto_lock_snapshot(auto_lock_seconds=120, idle_timer_disabled_before=False)
    begin = begin_backup_wake_policy(session_id="s1", device_name="ROB IPHONE")
    assert begin["active"] is True
    assert begin["pre_backup_snapshot"]["auto_lock_seconds"] == 120
    mid = power_policy_for_clients()
    assert mid["keep_awake"] is True
    assert mid["ios_disable_idle_timer"] is True
    assert mid["previous_auto_lock_seconds"] == 120
    assert any(n.get("kind") == "auto_lock_start" for n in mid.get("pending_notifications") or [])

    end = end_backup_wake_policy(reason="cancelled")
    assert end["active"] is False
    assert end["restored_auto_lock_seconds"] == 120
    assert end["restored_auto_lock_label"] == "2 Minutes"
    after = power_policy_for_clients()
    assert after["keep_awake"] is False
    assert after["ios_disable_idle_timer"] is False
    assert after["restore_to_seconds"] == 120
    assert any(n.get("kind") == "auto_lock_restore" for n in after.get("pending_notifications") or [])


def test_end_on_complete_uses_logged_value(cumulous_home):
    begin_backup_wake_policy(session_id="s2", device_name="iPhone", previous_auto_lock_seconds=0)
    end = end_backup_wake_policy(reason="complete")
    assert end["restored_auto_lock_label"] == "Never"


def test_begin_is_idempotent_and_drops_stale_restore(cumulous_home):
    begin_backup_wake_policy(session_id="s3", device_name="iPhone", previous_auto_lock_seconds=60)
    end_backup_wake_policy(reason="complete")  # false-complete noise
    # Re-engage mid-backup must keep awake and not surface restore push
    begin_backup_wake_policy(session_id="s3", device_name="iPhone")
    mid = power_policy_for_clients()
    assert mid["keep_awake"] is True
    assert mid["ios_reassert_interval_sec"] == 0.25
    assert not any(n.get("kind") == "auto_lock_restore" for n in mid.get("pending_notifications") or [])
