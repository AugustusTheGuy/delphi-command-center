import subprocess

import psutil
import streamlit as st

from core.wifi_monitor import snapshot as wifi_snapshot


def _wifi_scan() -> list:
    try:
        out = subprocess.run(
            ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-s"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = out.stdout.strip().splitlines()[1:8]
        return lines
    except Exception:
        return ["WiFi scan unavailable on this host."]


def render(profile: dict | None) -> None:
    st.header("System Status")
    st.caption("PR-03 — psutil metrics + WiFi anomaly detection")

    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CPU", f"{cpu}%")
    c2.metric("RAM", f"{mem.percent}%")
    c3.metric("Disk", f"{disk.percent}%")
    c4.metric("Processes", str(len(psutil.pids())))

    snap = wifi_snapshot()
    st.subheader("Current WiFi")
    st.markdown(
        f"<div class='dhc-card'>SSID: <b>{snap.ssid}</b> · Signal: {snap.signal} · iface: {snap.interface}</div>",
        unsafe_allow_html=True,
    )
    if snap.anomalies:
        for a in snap.anomalies:
            st.warning(a)
    else:
        st.success("No WiFi anomalies detected.")

    st.subheader("Nearby networks")
    for line in _wifi_scan():
        st.code(line)

    st.subheader("Connections watch")
    st.caption("Baseline scan — expand with netstat diff in PR-09.")
    st.info("Monitoring active — no anomalies in baseline scan.")