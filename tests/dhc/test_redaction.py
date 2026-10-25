from scripts.redact_docs import redact_text


def test_quoted_password_is_removed():
    raw = 'The account password is "correct-horse-battery" and stays quoted.'
    out = redact_text(raw)
    assert "correct-horse-battery" not in out
    assert "[redacted]" in out


def test_backtick_password_is_removed():
    raw = "password `correct-horse-battery` (change immediately)"
    assert "correct-horse-battery" not in redact_text(raw)
