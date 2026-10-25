from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_delphi_shell_stays_on_8501():
    text = (ROOT / "macos" / "main.swift").read_text()
    assert "let serverPort: UInt16 = 8501" in text
    assert '"--server.address", "127.0.0.1"' in text
    assert ".fullScreenAuxiliary" in text
    assert ".canJoinAllSpaces" in text
    assert "NSPanel" in text
    assert "panel.level = .floating" in text
    assert "panel.level = .normal" not in text
    assert "streamlit.pid" in text
    assert "nox_access.request" in text
    assert "moveToActiveSpace" not in text
    assert "NSApp.activate" not in text
