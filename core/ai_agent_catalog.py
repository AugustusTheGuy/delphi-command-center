"""Catalog of AI agents/tools for Delphi Nox Dark + DHC integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Runtime = Literal["local", "cloud", "hybrid", "prompt_only", "blocked_hw"]


@dataclass
class AgentIntegration:
    id: str
    name: str
    runtime: Runtime
    role: str
    install_path: str
    ollama_model: str | None = None
    route_keywords: list[str] = field(default_factory=list)
    prompt_file: str | None = None
    notes: str = ""


CATALOG: list[AgentIntegration] = [
    AgentIntegration("ollama", "Ollama", "local", "LLM runtime", "/opt/homebrew/bin/ollama", route_keywords=["ollama", "local model"]),
    AgentIntegration("mlx", "MLX (via Ollama preview)", "local", "Apple Silicon inference", "mlx-lm", route_keywords=["mlx", "apple silicon"]),
    AgentIntegration("hermes", "Hermes Router", "hybrid", "NL command router", "~/.config/hermes", "hermes3:8b", ["hermes", "route", "command"]),
    AgentIntegration("qwen", "Qwen 2.5 Coder", "local", "Coding + routing (light, fast)", "ollama:qwen2.5-coder:7b", "qwen2.5-coder:7b", ["code", "implement", "python", "git"]),
    AgentIntegration("qwen36", "Qwen 3.6 35B-A3B Heavy (MoE)", "local", "High-capability coding + reasoning (35B total params, only ~3B active per token)", "ollama:huihui_ai/qwen3.6-abliterated", "huihui_ai/qwen3.6-abliterated", ["heavy", "power", "qwen3", "qwen36", "35b", "moe", "advanced", "strong", "best quality", "deep reason"], notes="MoE already on ExternalSSD (23GB Q4). Stronger than 7B Qwen and competitive/superior to Qwythos on coding & general tasks per benchmarks. On 16GB M4: usable but slow first load (minutes from drive) and high memory use (~20GB+). Not daily default — trigger with keywords like 'heavy' or 'power'. Abliterated version (fewer refusals — review outputs)."),
    AgentIntegration("qwythos", "Qwythos-9B Mythos", "local", "Reasoning persona", "ollama:qwythos-9b", "qwythos-9b", ["reason", "mythos", "fable trace"]),
    AgentIntegration("gemma", "Gemma 2", "local", "Efficient general", "ollama:gemma2:9b", "gemma2:9b", ["summarize", "explain", "general"]),
    AgentIntegration("gemini", "Google Gemini", "cloud", "Cloud reasoning", "API", route_keywords=["gemini", "google ai"]),
    AgentIntegration("fable5", "Fable 5 Persona", "prompt_only", "CL4R1T4S system prompt", "~/DelphiAgents/prompts/claude-fable-5.md",
                     prompt_file="~/DelphiAgents/prompts/claude-fable-5.md", route_keywords=["fable", "advanced agent", "tool use"]),
    AgentIntegration("glm52", "GLM-5.2", "blocked_hw", "Requires 512GB+ Mac Studio", "mlx-community/GLM-5.2-DQ4plus-q8",
                     notes="NOT runnable on 16GB M4 — use Hermes+Qwen stack instead"),
    AgentIntegration("claude_code", "Claude Code", "cloud", "Heavy coding escalation", "claude", route_keywords=["claude code", "refactor", "pr"]),
    AgentIntegration("grok_build", "Grok Build", "cloud", "Agentic IDE", "~/.grok/bin/grok", route_keywords=["grok", "build"]),
    AgentIntegration("timecopilot", "TimeCopilot", "local", "Forecasting + anomaly agent", "~/AI/apps/timecopilot",
                     route_keywords=["forecast", "time series", "anomaly", "predict"]),
    AgentIntegration("phantomcloak", "PhantomCloak", "local", "DSI/VPN command center", "~/Desktop/PhantomCloak",
                     route_keywords=["vpn", "dsi", "cloak", "proxy", "residential"]),
    AgentIntegration("prompt_master", "prompt-master", "local", "Prompt optimization", "core/prompt_optimizer.py",
                     route_keywords=["optimize prompt", "prompt"]),
    AgentIntegration("vilix", "Vilix Memory", "local", "Shared persistent AI memory", "~/DelphiHomeController/data/vilix_memory.json",
                     route_keywords=["remember", "recall", "memory", "context"]),
    AgentIntegration("openhuman", "OpenHuman", "local", "Personal AI harness + Memory Tree", "/Applications/OpenHuman.app",
                     route_keywords=["openhuman", "memory tree", "vault", "digital labor", "super intelligence"],
                     notes="Sidecar to DHC — GPL-3.0; local Ollama provider only; workspace on ExternalSSD"),
    AgentIntegration("headr", "Headr", "local", "Token reduction", "pending", route_keywords=["compress", "token", "headr"]),
    AgentIntegration("perplexity", "Perplexity", "cloud", "Web research API", "API", route_keywords=["search web", "research", "perplexity"]),
    AgentIntegration("opencode", "OpenCode", "hybrid", "Open coding agent", "pending", route_keywords=["opencode"]),
    AgentIntegration("event_manager", "EventManager", "local", "Event-driven orchestration", "hooks/persistent_hooks.py",
                     route_keywords=["event", "trigger", "schedule", "catalog"]),
]


def by_id(agent_id: str) -> AgentIntegration | None:
    return next((a for a in CATALOG if a.id == agent_id), None)