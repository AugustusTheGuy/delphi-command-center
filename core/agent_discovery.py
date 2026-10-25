"""Discover installed AI agents on Mac + ExternalSSD at DHC startup."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from core.ai_agent_catalog import CATALOG, AgentIntegration
from core.ollama_client import is_available, list_models

REPORT_FILE = Path(__file__).resolve().parent.parent / "data" / "agent_discovery.json"
EXTERNALSSD = Path("/Volumes/ExternalSSD")


def _expand(p: str) -> Path:
    return Path(p.replace("~", str(Path.home())))


def _check_path(agent: AgentIntegration) -> bool:
    raw = agent.install_path
    if raw.startswith("ollama:") or raw in ("mlx-lm", "API", "pending"):
        return False
    p = _expand(raw)
    if p.is_file() or p.is_dir():
        return True
    return shutil.which(raw.split("/")[-1]) is not None


def discover() -> dict[str, Any]:
    ollama_up = is_available()
    ollama_models = list_models() if ollama_up else []
    nox_mounted = EXTERNALSSD.exists()

    agents: list[dict[str, Any]] = []
    for a in CATALOG:
        installed = a.runtime == "blocked_hw"
        if a.runtime == "blocked_hw":
            status = "blocked_hw"
        elif a.id == "ollama":
            installed = ollama_up or shutil.which("ollama") is not None
            status = "online" if ollama_up else ("installed" if installed else "missing")
        elif a.ollama_model:
            installed = a.ollama_model in ollama_models or any(
                m == a.ollama_model or m.startswith(f"{a.ollama_model}:")
                for m in ollama_models
            )
            status = "ready" if installed else "model_not_pulled"
        elif a.runtime == "prompt_only":
            installed = a.prompt_file and _expand(a.prompt_file).exists()
            status = "ready" if installed else "prompt_missing"
        elif a.id == "openhuman":
            app = Path("/Applications/OpenHuman.app")
            ws = EXTERNALSSD / "AI" / "openhuman-workspace"
            installed = app.exists()
            status = "ready" if installed else "missing"
            if installed and not ws.exists():
                status = "installed_no_workspace"
        elif a.runtime == "cloud":
            installed = _check_path(a) if a.install_path not in ("API",) else False
            status = "cloud_api"
        else:
            installed = _check_path(a)
            status = "ready" if installed else "missing"

        agents.append({
            "id": a.id,
            "name": a.name,
            "runtime": a.runtime,
            "installed": installed,
            "status": status,
            "notes": a.notes,
        })

    report = {
        "scanned_at": datetime.now().isoformat(),
        "hardware": {"chip": "Apple M4", "ram_gb": 16, "externalssd_mounted": nox_mounted},
        "ollama": {"online": ollama_up, "models": ollama_models},
        "agents": agents,
        "recommendation": _synergy_notes(agents, ollama_models),
    }
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2))
    return report


def _synergy_notes(agents: list[dict], models: list[str]) -> str:
    if any(a["id"] == "glm52" for a in agents):
        return (
            "GLM-5.2 blocked on 16GB RAM. Run Hermes → Ollama (qwen2.5 + gemma2 + hermes3). "
            "Store models on ExternalSSD via OLLAMA_MODELS."
        )
    if "qwen2.5-coder:7b" in models or "qwen2.5:7b-instruct" in str(models):
        return "Qwen stack ready for Central Command + Hermes router."
    return "Pull qwen2.5-coder:7b and gemma2:9b on ExternalSSD, then rerun discovery."


def run_discovery_hook() -> dict[str, Any]:
    return discover()