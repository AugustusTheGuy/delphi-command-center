"""50 agents + Project Manager for Cumulous Cloud program dashboard."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    squad: str
    role: str
    status: str = "planned"  # idle | active | planned | blocked
    progress_pct: float = 0.0
    grade_pct: float | None = None


def _a(n: int, name: str, squad: str, role: str, status: str = "planned") -> AgentSpec:
    return AgentSpec(f"agent-{n:02d}", name, squad, role, status)


AGENTS: tuple[AgentSpec, ...] = (
    _a(1, "Orchestrator Lead", "Program", "program", "active"),
    _a(2, "Requirements Archivist", "Program", "program", "active"),
    _a(3, "CEO Briefing Agent", "Program", "program", "active"),
    _a(4, "UX/UI Design Lead", "Platform", "design", "active"),
    _a(5, "SwiftUI iOS Lead", "Platform", "ios", "active"),
    _a(6, "Streamlit Admin Shell", "Platform", "mac", "active"),
    _a(7, "py2app Packaging", "Platform", "mac", "active"),
    _a(8, "Accessibility Agent", "Platform", "qa"),
    _a(9, "Auth & Profiles", "Security", "auth", "active"),
    _a(10, "Encryption Hardening", "Security", "crypto", "active"),
    _a(11, "Shared TOTP Agent", "Security", "crypto", "active"),
    _a(12, "Challenge Fanout Agent", "Security", "notify", "active"),
    _a(13, "Lockout Policy Agent", "Security", "auth", "active"),
    _a(14, "Audit Log Agent", "Security", "audit"),
    _a(15, "Progressive Storage Architect", "Storage", "backup", "active"),
    _a(16, "Space/GC Optimizer", "Storage", "backup", "active"),
    _a(17, "Device Bridge Verifier", "Storage", "verify", "active"),
    _a(18, "SMS/Notes Ingest", "Storage", "backup"),
    _a(19, "System Backup Path", "Storage", "idevice", "active"),
    _a(20, "Nextcloud WebDAV", "Storage", "cloud"),
    _a(21, "ExternalSSD Plane Agent", "Storage", "storage", "active"),
    _a(22, "Secrets Hygiene", "Security", "secrets", "active"),
    _a(23, "CEO Override Flow", "Security", "auth", "active"),
    _a(24, "BEARACCOUNT Agent", "Security", "auth", "active"),
    _a(25, "Site Policy Agent", "Ops", "policy", "active"),
    _a(26, "Cellular Sync Agent", "Ops", "network"),
    _a(27, "Schedule/Midnight Agent", "Ops", "schedule", "active"),
    _a(28, "Persistent Change Hook", "Ops", "schedule", "active"),
    _a(29, "FastAPI Bridge", "DevOps", "api", "active"),
    _a(30, "Mac Companion CLI", "DevOps", "companion", "active"),
    _a(31, "Tailscale Access", "DevOps", "network"),
    _a(32, "Tool Auto-Install", "DevOps", "setup", "active"),
    _a(33, "MLX Vision Scoring", "AI Core", "vision"),
    _a(34, "Gemma Vision Wire", "AI Core", "vision"),
    _a(35, "Prioritization Engine", "AI Core", "mlx"),
    _a(36, "CardSession UX Polish", "Platform", "ios", "active"),
    _a(37, "Settings Robustness", "Platform", "ios", "active"),
    _a(38, "Splash Branding", "Platform", "design"),
    _a(39, "HA Confirm Notify", "Home", "ha"),
    _a(40, "PhantomCloak Caller", "Security", "privacy"),
    _a(41, "Multi-Device Inventory", "Mobile", "devices", "active"),
    _a(42, "iPhone Pairing", "Mobile", "ios", "active"),
    _a(43, "Background Upload", "Mobile", "ios"),
    _a(44, "Push Notify Relay", "Mobile", "notify", "active"),
    _a(45, "QA Dashboard", "Platform", "qa", "active"),
    _a(46, "Performance Profiler", "Platform", "qa"),
    _a(47, "Security Auditor", "Security", "audit", "active"),
    _a(48, "Stress Test Agent", "Platform", "qa"),
    _a(49, "Docs & CEO Manual", "Program", "docs", "active"),
    _a(50, "Distribution Prep", "Program", "release"),
)

PROJECT_MANAGER = AgentSpec(
    id="pm-00",
    name="Project Manager",
    squad="Program",
    role="pm",
    status="active",
    progress_pct=0.0,
    grade_pct=None,
)


def all_agents() -> list[AgentSpec]:
    return list(AGENTS)


def roster_count() -> dict:
    return {
        "agents": len(AGENTS),
        "pm_present": True,
        "pm_id": PROJECT_MANAGER.id,
        "total_with_pm": len(AGENTS) + 1,
    }


def dashboard_rows() -> list[dict]:
    rows = [asdict(a) for a in AGENTS]
    rows.append(asdict(PROJECT_MANAGER))
    return rows
