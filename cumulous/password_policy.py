"""Password rules: 8+ chars, one number, one symbol."""

from __future__ import annotations

import re
import string


def validate_password(password: str) -> tuple[bool, str]:
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not re.search(r"\d", password):
        return False, "Password must include at least one number."
    if not any(c in string.punctuation for c in password):
        return False, "Password must include at least one symbol."
    return True, "ok"
