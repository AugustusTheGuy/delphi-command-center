"""Prompt optimization for orchestrator (PR-02)."""
from __future__ import annotations

from core.ollama_client import generate, is_available


def optimize_prompt(raw: str, model: str = "hermes3:8b") -> str:
    if not raw.strip():
        return raw
    if not is_available():
        return _heuristic_optimize(raw)
    system = (
        "You are a prompt engineer for a home automation and AI orchestration system. "
        "Rewrite the user prompt to be clear, actionable, and safe. Output only the optimized prompt."
    )
    result = generate(
        f"Optimize this prompt:\n\n{raw}",
        model=model,
        system=system,
    )
    text = result.get("response", "").strip()
    return text or _heuristic_optimize(raw)


def _heuristic_optimize(raw: str) -> str:
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    bullets = "\n".join(f"- {ln}" if not ln.startswith("-") else ln for ln in lines)
    return (
        "Context: Delphi Home Control command center.\n"
        "Objective:\n"
        f"{bullets}\n"
        "Constraints: local-first, secure defaults, no destructive actions without confirmation."
    )