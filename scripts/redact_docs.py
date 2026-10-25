"""Replace quoted credential values in documents. Never prints the values."""

from __future__ import annotations

import re
from pathlib import Path

SKIP_PARTS = {".venv", ".venv-mlx", "node_modules", "ios", "dist", ".firecrawl"}
PLACEHOLDERS = {"your-secure-password", "changeme", "[redacted]"}

_QUOTED = re.compile(r'(?i)(password(?: is)?\s+)"([^"]+)"')
_TICKED = re.compile(r"(?i)(password(?: is)?\s+)`([^`]+)`")
_ASSIGNED = re.compile(r'(?i)((?:api[_-]?key|secret|token)\s*[:=]\s*)["\']([^"\']+)["\']')


def _keep(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered in PLACEHOLDERS or value.startswith("$") or value.startswith("<")


def _swap(match: re.Match, wrapper: str) -> str:
    value = match.group(2)
    if _keep(value):
        return match.group(0)
    if wrapper == "tick":
        return f"{match.group(1)}`[redacted]`"
    return f'{match.group(1)}"[redacted]"'


def redact_text(text: str) -> str:
    text = _QUOTED.sub(lambda match: _swap(match, "quote"), text)
    text = _TICKED.sub(lambda match: _swap(match, "tick"), text)
    text = _ASSIGNED.sub(lambda match: _swap(match, "quote"), text)
    return text


def redact_tree(root: Path) -> list[str]:
    changed: list[str] = []
    for path in root.rglob("*"):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        if path.stat().st_size > 2_000_000:
            continue
        original = path.read_text(errors="ignore")
        updated = redact_text(original)
        if updated != original:
            path.write_text(updated)
            changed.append(str(path))
    return changed


if __name__ == "__main__":
    home = Path(__file__).resolve().parents[1]
    files = redact_tree(home)
    print(f"files_changed {len(files)}")
    for name in files:
        print(name)
