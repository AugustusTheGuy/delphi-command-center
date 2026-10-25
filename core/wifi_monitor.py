"""WiFi / network anomaly hints (PR-03)."""
from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass


@dataclass
class WifiSnapshot:
    interface: str
    ssid: str
    signal: str
    anomalies: list[str]


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=10)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def snapshot() -> WifiSnapshot:
    system = platform.system()
    iface = "en0" if system == "Darwin" else "wlan0"
    ssid, signal = "", "unknown"
    anomalies: list[str] = []

    if system == "Darwin":
        out = _run(["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"])
        if not out:
            out = _run(["networksetup", "-getairportnetwork", iface])
        for line in out.splitlines():
            if " SSID:" in line or "SSID:" in line:
                ssid = line.split(":", 1)[-1].strip()
            if "agrCtlRSSI" in line or "RSSI" in line:
                m = re.search(r"-?\d+", line)
                if m:
                    signal = f"{m.group()} dBm"
                    rssi = int(m.group())
                    if rssi < -75:
                        anomalies.append("Weak signal — consider mesh node or AP relocation")
    else:
        out = _run(["iwconfig", iface])
        if "ESSID" in out:
            m = re.search(r'ESSID:"([^"]*)"', out)
            if m:
                ssid = m.group(1)
        if "Signal level" in out:
            signal = out.split("Signal level=")[-1].split()[0]

    if not ssid:
        anomalies.append("No WiFi association detected")
    return WifiSnapshot(interface=iface, ssid=ssid or "(none)", signal=signal, anomalies=anomalies)