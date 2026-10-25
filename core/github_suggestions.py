"""Dynamic GitHub / HuggingFace suggestions (PR-06)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

STATIC_GITHUB = [
    ("CrewAI", "Multi-agent orchestration framework", "crewAIInc/crewAI"),
    ("Open WebUI", "Chat UI for Ollama/MLX models", "open-webui/open-webui"),
    ("home-assistant/core", "Smart home hub", "home-assistant/core"),
    ("immich-app/immich", "Self-hosted Google Photos", "immich-app/immich"),
    ("jellyfin/jellyfin", "Media server for Samsung TVs", "jellyfin/jellyfin"),
    ("n8n-io/n8n", "Workflow automation", "n8n-io/n8n"),
    ("Mintplex-Labs/anything-llm", "RAG + agents", "Mintplex-Labs/anything-llm"),
    ("mudler/LocalAI", "Local OpenAI-compatible server", "mudler/LocalAI"),
    ("Qdrant/qdrant", "Vector DB for agent memory", "qdrant/qdrant"),
    ("usehomarr/homarr", "Service dashboard", "homarr-labs/homarr"),
]

STATIC_HF = [
    ("Qwen2.5", "Coding + agent models", "Qwen/Qwen2.5-Coder-7B-Instruct"),
    ("smolagents", "HuggingFace agents toolkit", "huggingface/smolagents"),
    ("mistralai/Mistral", "General reasoning", "mistralai/Mistral-7B-Instruct-v0.3"),
    ("google/gemma-2", "Efficient local models", "google/gemma-2-2b-it"),
    ("sentence-transformers", "Embeddings for RAG", "sentence-transformers/all-MiniLM-L6-v2"),
    ("microsoft/Phi-3", "Small capable models", "microsoft/Phi-3-mini-4k-instruct"),
    ("openai/whisper-large-v3", "Voice → command", "openai/whisper-large-v3"),
    ("meta-llama/Llama-3", "General purpose", "meta-llama/Meta-Llama-3-8B-Instruct"),
    ("HuggingFaceTB/SmolVLM", "Vision tasks", "HuggingFaceTB/SmolVLM-Instruct"),
    ("deepseek-ai/DeepSeek-Coder", "Code generation", "deepseek-ai/deepseek-coder-6.7b-instruct"),
]


def github_stars(repo: str) -> int | None:
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "DelphiHomeController"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        return int(data.get("stargazers_count", 0))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def enrich_github() -> list[dict[str, Any]]:
    out = []
    for name, desc, repo in STATIC_GITHUB:
        stars = github_stars(repo)
        out.append({"name": name, "desc": desc, "repo": repo, "stars": stars})
    return out


def list_hf() -> list[dict[str, str]]:
    return [{"name": n, "desc": d, "model_id": m} for n, d, m in STATIC_HF]