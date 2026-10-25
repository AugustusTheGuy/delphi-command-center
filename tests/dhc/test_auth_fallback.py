import json

from core import auth


def test_open_local_session_has_no_password(tmp_path, monkeypatch):
    monkeypatch.delenv("DHC_ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(auth, "DATA_DIR", tmp_path)
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_FILE", tmp_path / ".auth_secret")
    auth.ensure_default_user()
    data = json.loads((tmp_path / "users.json").read_text())
    assert data["users"][0]["username"] == "DelphiBEAR"
    assert "password_hash" not in data["users"][0]
    assert auth.authenticate("DelphiBEAR", "") is True
    assert auth.authenticate("DelphiBEAR", "nope") is True
