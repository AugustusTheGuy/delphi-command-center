"""Multi-layer USB / usbmux / pair detection status matrix."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "cumulous_home"
    home.mkdir()
    monkeypatch.setenv("CUMULOUS_HOME", str(home))
    monkeypatch.setenv("CUMULOUS_FORCE_INTERNAL_VAULT", "1")
    # Reset injectable runner between tests
    import cumulous.devices as devices

    devices._RUN = None
    yield home
    devices._RUN = None


def _cp(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_empty_stack_no_iphone(isolated_home, monkeypatch):
    import cumulous.devices as devices

    def fake_run(args, **kwargs):
        cmd = args[0] if args else ""
        if "idevice_id" in args:
            return _cp("")
        if "system_profiler" in args:
            return _cp("USB:\n\n    USB 3.1 Bus:\n\n")
        if "ioreg" in args:
            return _cp("")
        if "idevicepair" in args:
            return _cp("")
        return _cp("")

    devices._RUN = fake_run
    monkeypatch.setattr(devices.shutil, "which", lambda c: f"/usr/bin/{c}")

    inv = devices.device_inventory(user_says_plugged=False)
    assert inv["usbmux_seen"] is False
    assert inv["usb_iphone_seen"] is False
    assert inv["trust_needed"] is False
    assert inv["cable_or_power_only"] is False
    assert inv["connected"] == []
    assert "No iPhone" in inv["status_line"]


def test_cable_or_power_only_when_user_says_plugged(isolated_home, monkeypatch):
    import cumulous.devices as devices

    def fake_run(args, **kwargs):
        return _cp("")

    devices._RUN = fake_run
    monkeypatch.setattr(devices.shutil, "which", lambda c: f"/usr/bin/{c}")

    inv = devices.device_inventory(user_says_plugged=True)
    assert inv["cable_or_power_only"] is True
    assert "does not see" in inv["status_line"].lower() or "USB" in inv["status_line"]


def test_usb_product_without_udid_means_trust_needed(isolated_home, monkeypatch):
    import cumulous.devices as devices

    profiler = """
USB:

    USB 3.1 Bus:

      Host Controller Driver: AppleUSBXHCIPCI

        iPhone:

          Product ID: 0x12a8
          Vendor ID: 0x05ac (Apple Inc.)
          Product Name: iPhone
          Serial Number: F2LDXXXXX
"""

    def fake_run(args, **kwargs):
        if "idevice_id" in args:
            return _cp("")
        if "system_profiler" in args:
            return _cp(profiler)
        if "idevicepair" in args:
            return _cp("")
        return _cp("")

    devices._RUN = fake_run
    monkeypatch.setattr(devices.shutil, "which", lambda c: f"/usr/bin/{c}")

    inv = devices.device_inventory()
    assert inv["usb_iphone_seen"] is True
    assert inv["usbmux_seen"] is False
    assert inv["trust_needed"] is True
    assert inv["primary_probe"] is None
    assert "Trust" in inv["status_line"] or "trust" in inv["status_line"].lower() or "unlock" in inv["status_line"].lower()


def test_usbmux_udid_connected_and_probe(isolated_home, monkeypatch):
    import cumulous.devices as devices

    udid = "00008110aabbccddeeff00112233445566778899"

    def fake_run(args, **kwargs):
        if args[:2] == ["idevice_id", "-l"] or (args and args[0] == "idevice_id"):
            return _cp(udid + "\n")
        if "ideviceinfo" in args:
            key = args[args.index("-k") + 1] if "-k" in args else ""
            mapping = {
                "DeviceName": "CEO iPhone",
                "ProductType": "iPhone15,3",
                "InternationalMobileEquipmentIdentity": "356938035643809",
                "PhoneNumber": "+15551212",
                "SerialNumber": "F2LDTEST",
                "ModelNumber": "MQ8R3",
            }
            return _cp(mapping.get(key, ""))
        if "system_profiler" in args:
            return _cp("")
        if "idevicepair" in args and "list" in args:
            return _cp(udid + "\n")
        return _cp("")

    devices._RUN = fake_run
    monkeypatch.setattr(devices.shutil, "which", lambda c: f"/usr/bin/{c}")

    inv = devices.device_inventory()
    assert inv["usbmux_seen"] is True
    assert inv["trust_needed"] is False
    assert inv["primary_probe"] is not None
    assert inv["primary_probe"]["display_name"] == "CEO iPhone"
    assert inv["primary_probe"]["imei"] == "356938035643809"
    assert inv["primary_probe"]["udid"] == udid

    probe = devices.probe_connected_device()
    assert probe is not None
    assert probe["display_name"] == "CEO iPhone"
    assert probe["device_id"] == "356938035643809"


def test_paired_list_and_related_union(isolated_home, monkeypatch):
    import cumulous.devices as devices

    paired_udid = "aaaabbbbccccddddeeeeffff0000111122223333"
    devices.register_device(
        "reg-dev-1",
        display_name="Registered Phone",
        owner_username="DelphiBEAR",
        udid="regudid9999888877776666555544443333",
    )

    def fake_run(args, **kwargs):
        if "idevice_id" in args:
            return _cp("")
        if "system_profiler" in args:
            return _cp("")
        if "idevicepair" in args:
            return _cp(f"{paired_udid} - SUCCESS\n")
        return _cp("")

    devices._RUN = fake_run
    monkeypatch.setattr(devices.shutil, "which", lambda c: f"/usr/bin/{c}")

    inv = devices.device_inventory()
    assert any(p["device_id"] == paired_udid for p in inv["paired_on_mac"])
    assert any(r.get("display_name") == "Registered Phone" for r in inv["registered"])
    keys = {r.get("udid") or r.get("device_id") for r in inv["related_devices"]}
    assert paired_udid in keys
    assert "regudid9999888877776666555544443333" in keys or "reg-dev-1" in keys


def test_attempt_pair_trust_needed(isolated_home, monkeypatch):
    import cumulous.devices as devices

    def fake_run(args, **kwargs):
        if "validate" in args:
            return _cp(stderr="Invalid host id", returncode=1)
        if "pair" in args:
            return _cp(stderr="ERROR: Please accept the trust dialog on the device.", returncode=1)
        return _cp("")

    devices._RUN = fake_run
    monkeypatch.setattr(devices.shutil, "which", lambda c: f"/usr/bin/{c}")

    res = devices.attempt_pair("deadbeef")
    assert res["ok"] is False
    # either trust_needed or failed with helpful message
    assert res.get("message")


def test_attempt_pair_success(isolated_home, monkeypatch):
    import cumulous.devices as devices

    def fake_run(args, **kwargs):
        if "validate" in args:
            return _cp(stdout="SUCCESS: Validated pairing with device deadbeef", returncode=0)
        return _cp("")

    devices._RUN = fake_run
    monkeypatch.setattr(devices.shutil, "which", lambda c: f"/usr/bin/{c}")

    res = devices.attempt_pair("deadbeef")
    assert res["ok"] is True


def test_apple_account_label_roundtrip(isolated_home, monkeypatch):
    import cumulous.devices as devices

    devices._RUN = lambda args, **kw: _cp("")
    monkeypatch.setattr(devices.shutil, "which", lambda c: f"/usr/bin/{c}")

    assert devices.apple_account_label() == ""
    devices.set_apple_account_label("ceo@example.local")
    assert devices.apple_account_label() == "ceo@example.local"
    inv = devices.device_inventory()
    assert inv["apple_account_label"] == "ceo@example.local"
