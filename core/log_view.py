"""Show the server log with secrets removed."""

from __future__ import annotations

import re
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent.parent / "data" / "logs" / "delphi-server.log"

_SECRET = re.compile(
    r"(?i)([A-Za-z0-9_-]*(?:api[_-]?key|token|password|secret)[A-Za-z0-9_-]*\s*[=:]\s*)(\S+)"
)
_BEARER = re.compile(r"(?i)(Authorization\s*:\s*Bearer\s+)(\S+)")


def redact_log(text: str) -> str:
    cleaned = _BEARER.sub(r"\1[redacted]", text)
    return _SECRET.sub(r"\1[redacted]", cleaned)


def server_log_text(limit: int = 80) -> str:
    if not LOG_FILE.exists():
        return "No server log yet."
    try:
        lines = LOG_FILE.read_text(errors="replace").splitlines()
    except OSError:
        return "The server log could not be read."
    return redact_log("\n".join(lines[-limit:]))
