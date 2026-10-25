"""Ollama local LLM client (PR-02)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_HOST = "http://127.0.0.1:11434"


def list_models(host: str = DEFAULT_HOST) -> list[str]:
    try:
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return [m.get("name", "") for m in data.get("models", [])]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []


def generate(
    prompt: str,
    model: str = "llama3.2",
    host: str = DEFAULT_HOST,
    system: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"error": str(e), "response": ""}
    except json.JSONDecodeError:
        return {"error": "Invalid JSON from Ollama", "response": ""}


def is_available(host: str = DEFAULT_HOST) -> bool:
    try:
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False