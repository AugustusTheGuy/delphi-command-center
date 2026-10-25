"""One short line for the front page when local AI is off. The check is remembered for half a minute."""

from __future__ import annotations

import time
import urllib.error
import urllib.request

from core.ollama_client import DEFAULT_HOST

_CACHE = {"at": 0.0, "value": None}


def _quick_check() -> bool:
    try:
        req = urllib.request.Request(f"{DEFAULT_HOST}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=0.4) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def local_ai_line(now: float | None = None, check=None) -> str | None:
    clock = time.time() if now is None else now
    probe = check or _quick_check
    cached = _CACHE["value"]
    if cached is not None and clock - _CACHE["at"] < 30:
        available = cached
    else:
        available = bool(probe())
        _CACHE["at"] = clock
        _CACHE["value"] = available
    if available:
        return None
    return "Local AI is off."


def clear_ai_cache() -> None:
    _CACHE["at"] = 0.0
    _CACHE["value"] = None
