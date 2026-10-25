"""Resolve agent routes to Ollama models and run inference."""

from __future__ import annotations

from dataclasses import dataclass

from core.ai_agent_catalog import CATALOG, by_id
from core.ollama_client import generate, is_available, list_models


@dataclass
class AgentRunResult:
    agent_id: str
    agent_name: str
    model: str | None
    response: str
    error: str | None = None
    skipped: bool = False
    skip_reason: str = ""


def _model_installed(model: str) -> bool:
    models = list_models()
    return model in models or any(m == model or m.startswith(f"{model}:") for m in models)


def resolve_model(agent_id: str) -> str | None:
    agent = by_id(agent_id)
    if not agent or not agent.ollama_model:
        return None
    model = agent.ollama_model
    if _model_installed(model):
        models = list_models()
        exact = next((m for m in models if m == model or m.startswith(f"{model}:")), model)
        return exact
    return None


def run_agent_prompt(agent_id: str, prompt: str, *, timeout_model: str | None = None) -> AgentRunResult:
    agent = by_id(agent_id)
    name = agent.name if agent else agent_id

    if not is_available():
        return AgentRunResult(
            agent_id=agent_id,
            agent_name=name,
            model=None,
            response="",
            error="Ollama is offline. Start Ollama and retry.",
        )

    model = timeout_model or resolve_model(agent_id)
    if not model:
        return AgentRunResult(
            agent_id=agent_id,
            agent_name=name,
            model=None,
            response="",
            skipped=True,
            skip_reason=f"{name} has no local Ollama model — routed prompt only.",
        )

    result = generate(prompt, model=model)
    if result.get("error"):
        return AgentRunResult(
            agent_id=agent_id,
            agent_name=name,
            model=model,
            response="",
            error=str(result["error"]),
        )

    text = (result.get("response") or "").strip()
    return AgentRunResult(
        agent_id=agent_id,
        agent_name=name,
        model=model,
        response=text or "(empty response)",
    )


def runnable_agent_ids() -> list[str]:
    if not is_available():
        return []
    return [a.id for a in CATALOG if a.ollama_model and resolve_model(a.id)]