"""50-agent roster for Delphi: Home Control program."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    squad: str
    pr: str
    model: str
    status: str  # idle | active | planned | blocked


def _a(n: int, name: str, squad: str, pr: str, model: str = "ollama", status: str = "planned") -> AgentSpec:
    return AgentSpec(f"agent-{n:02d}", name, squad, pr, model, status)


# Original 15 agents (PR-01 foundation + PR-02–06 owners)
_ORIGINAL = [
    _a(1, "Orchestrator Lead", "Program", "PR-01", "crewai", "active"),
    _a(2, "Requirements Archivist", "Program", "PR-01", "mlx-local", "active"),
    _a(3, "UX/UI Design Lead", "Platform", "PR-01", "ollama", "active"),
    _a(4, "Streamlit Platform Engineer", "Platform", "PR-01", "ollama", "active"),
    _a(5, "Auth & Profiles Agent", "Security", "PR-01", "ollama", "active"),
    _a(6, "AI Orchestrator Agent", "AI Core", "PR-02", "crewai", "active"),
    _a(7, "Central Command Agent", "AI Core", "PR-02", "ollama", "active"),
    _a(8, "System Monitor Agent", "Ops", "PR-03", "ollama", "active"),
    _a(9, "Project Management Agent", "Ops", "PR-03", "ollama", "active"),
    _a(10, "Home & TV Agent", "Home", "PR-04", "crewai", "active"),
    _a(11, "Nextcloud & Storage Agent", "Home", "PR-04", "ollama", "active"),
    _a(12, "Gaming Library Agent", "Lifestyle", "PR-05", "ollama", "planned"),
    _a(13, "OS Management Agent", "Ops", "PR-05", "terminal", "active"),
    _a(15, "Security & DevOps Agent", "Security", "PR-06", "terminal", "active"),
]

# 35 expansion agents (PR-07–PR-10 + specialization lanes)
_EXPANSION = [
    _a(16, "CrewAI Wiring Agent", "AI Core", "PR-08", "crewai"),
    _a(17, "MLX Router Agent", "AI Core", "PR-08", "mlx-local"),
    _a(18, "Ollama Model Curator", "AI Core", "PR-08", "ollama"),
    _a(19, "Prompt Memory Agent", "AI Core", "PR-02", "ollama"),
    _a(20, "Voice Command Agent", "AI Core", "PR-10", "whisper"),
    _a(21, "RAG Index Agent", "AI Core", "PR-08", "qdrant"),
    _a(22, "Fable Persona Agent", "AI Core", "PR-02", "ollama", "idle"),
    _a(23, "Docker Compose Agent", "DevOps", "PR-07", "terminal"),
    _a(24, "Home Assistant Integrator", "Home", "PR-04", "ha-api"),
    _a(25, "Samsung TV Control Agent", "Home", "PR-04", "ha-api"),
    _a(26, "HomeKit Bridge Agent", "Home", "PR-04", "homekit"),
    _a(27, "Immich Media Agent", "Home", "PR-07", "docker"),
    _a(28, "Jellyfin Cast Agent", "Home", "PR-07", "docker"),
    _a(29, "n8n Workflow Agent", "Home", "PR-07", "n8n"),
    _a(30, "Tailscale Access Agent", "DevOps", "PR-10", "tailscale"),
    _a(31, "iPhone Shortcuts Agent", "Mobile", "PR-10", "shortcuts"),
    _a(32, "WiFi Anomaly Agent", "Ops", "PR-03", "ollama", "active"),
    _a(33, "Terminal Sandbox Agent", "Ops", "PR-03", "terminal", "active"),
    _a(34, "GitHub Scout Agent", "Research", "PR-06", "firecrawl"),
    _a(35, "HuggingFace Scout Agent", "Research", "PR-06", "firecrawl"),
    _a(37, "Encryption Hardening Agent", "Security", "PR-09", "openssl"),
    _a(38, "Audit Log Agent", "Security", "PR-09", "ollama"),
    _a(39, "Backup Orchestrator", "Storage", "PR-04", "nextcloud"),
    _a(40, "Seagate Health Agent", "Storage", "PR-04", "smartctl"),
    _a(41, "RetroArch Launcher", "Lifestyle", "PR-05", "retroarch"),
    _a(42, "Controller Mapping Agent", "Lifestyle", "PR-05", "hidapi"),
    _a(43, "Media Licensing Policy Agent", "Lifestyle", "PR-05", "ollama"),
    _a(44, "OS Reversal Safety Agent", "Ops", "PR-05", "terminal", "active"),
    _a(45, "Project Template Agent", "Ops", "PR-03", "ollama"),
    _a(46, "Competitive Intel Agent", "Research", "PR-06", "firecrawl"),
    _a(47, "QA Dashboard Agent", "Platform", "PR-03", "firecrawl"),
    _a(48, "Accessibility Agent", "Platform", "PR-09", "ollama"),
    _a(49, "Performance Profiler", "Platform", "PR-09", "psutil"),
    _a(50, "CEO Briefing Agent", "Program", "PR-10", "ollama", "idle"),
]

AGENTS: tuple[AgentSpec, ...] = tuple(_ORIGINAL + _EXPANSION)


def iter_agents() -> Iterator[AgentSpec]:
    yield from AGENTS


def agents_by_pr(pr: str) -> list[AgentSpec]:
    return [a for a in AGENTS if a.pr == pr]


def agents_by_squad(squad: str) -> list[AgentSpec]:
    return [a for a in AGENTS if a.squad == squad]


def summary_stats() -> dict[str, int]:
    return {
        "total": len(AGENTS),
        "active": sum(1 for a in AGENTS if a.status == "active"),
        "idle": sum(1 for a in AGENTS if a.status == "idle"),
        "planned": sum(1 for a in AGENTS if a.status == "planned"),
        "blocked": sum(1 for a in AGENTS if a.status == "blocked"),
    }