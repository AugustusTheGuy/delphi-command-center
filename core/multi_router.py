"""Multi-agent router — per-agent optimized prompts + hook payloads."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.ai_agent_catalog import CATALOG
from core.prompt_optimizer import optimize_prompt


@dataclass
class RoutedPrompt:
    agent_id: str
    agent_name: str
    optimized_prompt: str
    hook_payload: dict = field(default_factory=dict)
    is_hook: bool = False


def _match_agents(text: str) -> list[str]:
    lower = text.lower()
    hits: list[str] = []
    for a in CATALOG:
        if any(kw in lower for kw in a.route_keywords):
            hits.append(a.id)
    if not hits:
        if any(k in lower for k in ("home", "tv", "light", "samsung")):
            hits.append("hermes")
        elif any(k in lower for k in ("vpn", "cloak", "proxy")):
            hits.append("phantomcloak")
        elif any(k in lower for k in ("forecast", "predict", "anomaly")):
            hits.append("timecopilot")
        elif any(k in lower for k in ("code", "implement", "fix bug")):
            hits.extend(["qwen", "claude_code"])
            if any(k in lower for k in ("heavy", "power", "advanced", "strong", "best", "qwen3", "35b", "moe")):
                hits.append("qwen36")
        else:
            hits.extend(["hermes", "qwen"])
    # Deduplicate preserve order
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h not in seen and h != "glm52":
            seen.add(h)
            out.append(h)
    return out[:5]


def _agent_system_hint(agent_id: str) -> str:
    hints = {
        "hermes": "You are Hermes, Delphi's local command router. Output actionable shell/HA steps.",
        "qwen": "You are Qwen Coder (light fast version). Output production Python/bash with safety checks.",
        "qwen36": "You are the powerful Qwen 3.6 35B-A3B MoE brain (heavy high-quality). Give detailed, high-capability answers, code, and reasoning. Only use when user asks for advanced or heavy analysis.",
        "fable5": "You are Fable Agent per CL4R1T4S persona — tool-aware, cite sources, safety first.",
        "phantomcloak": "You are PhantomCloak assistant. VPN/DSI profile and residential pool guidance.",
        "timecopilot": "You are TimeCopilot. Suggest forecasting/anomaly steps when time-series relevant.",
        "vilix": "Persist key facts to shared memory; recall prior Delphi context.",
        "prompt_master": "Optimize this prompt for clarity and routing before execution.",
        "gemma": "Concise general reasoning for home automation context.",
        "claude_code": "Escalation: multi-file refactor plan for Claude Code CLI.",
        "grok_build": "Escalation: agentic implementation plan for Grok Build.",
    }
    return hints.get(agent_id, "Delphi Home Control agent.")


def route_multi(raw: str, use_optimizer: bool = True) -> list[RoutedPrompt]:
    agent_ids = _match_agents(raw)
    results: list[RoutedPrompt] = []
    for aid in agent_ids:
        agent = next((a for a in CATALOG if a.id == aid), None)
        name = agent.name if agent else aid
        wrapped = f"{_agent_system_hint(aid)}\n\nUser request:\n{raw}"
        optimized = optimize_prompt(wrapped) if use_optimizer else wrapped
        hook = {
            "agent_id": aid,
            "trigger": "central_command",
            "persist": aid in ("vilix", "timecopilot", "event_manager"),
            "payload": raw[:500],
        }
        results.append(RoutedPrompt(
            agent_id=aid,
            agent_name=name,
            optimized_prompt=optimized,
            hook_payload=hook,
            is_hook=aid in ("timecopilot", "event_manager", "vilix"),
        ))
    return results