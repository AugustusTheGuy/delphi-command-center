"""Home Assistant API client (PR-04)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = os.environ.get("HA_URL", "http://localhost:8123")
DEFAULT_TOKEN = os.environ.get("HA_TOKEN", "")


def _request(path: str, method: str = "GET", body: dict | None = None) -> dict[str, Any]:
    url = f"{DEFAULT_URL.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json"}
    if DEFAULT_TOKEN:
        headers["Authorization"] = f"Bearer {DEFAULT_TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.URLError as e:
        return {"error": str(e)}
    except json.JSONDecodeError:
        return {"error": "Invalid JSON from Home Assistant"}


def ping() -> bool:
    result = _request("/api/")
    return "message" in result or result.get("ok")


def list_states() -> list[dict[str, Any]]:
    result = _request("/api/states")
    return result if isinstance(result, list) else []


def call_service(domain: str, service: str, entity_id: str | None = None, data: dict | None = None) -> dict[str, Any]:
    payload = dict(data or {})
    if entity_id:
        payload["entity_id"] = entity_id
    return _request(f"/api/services/{domain}/{service}", method="POST", body=payload)


def run_scene(name: str, entities: list[str]) -> dict[str, Any]:
    """Best-effort scene trigger — requires matching HA scene/automation."""
    return call_service("script", "turn_on", data={"variables": {"scene": name, "entities": entities}})