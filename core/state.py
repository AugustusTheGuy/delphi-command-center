"""Persistent session-adjacent state helpers."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TASKS_FILE = DATA_DIR / "agent_tasks.json"
OPS_FILE = DATA_DIR / "completed_operations.json"
PROJECTS_ROOT = DATA_DIR / "projects"


def _load_json(path: Path, default: Any) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def log_agent_task(agent: str, task: str, status: str = "in_process", language: str = "") -> None:
    tasks = _load_json(TASKS_FILE, {"active": [], "history": []})
    entry = {
        "agent": agent,
        "task": task,
        "status": status,
        "language": language,
        "timestamp": datetime.now().isoformat(),
    }
    if status == "in_process":
        tasks["active"].append(entry)
    else:
        tasks["active"] = [t for t in tasks["active"] if t.get("task") != task]
        tasks["history"].insert(0, entry)
        tasks["history"] = tasks["history"][:500]
    _save_json(TASKS_FILE, tasks)


def get_agent_tasks() -> Dict[str, List]:
    return _load_json(TASKS_FILE, {"active": [], "history": []})


def log_operation(title: str, initial_impact: str, current_impact: str, reversible: bool = True) -> None:
    ops = _load_json(OPS_FILE, [])
    ops.insert(0, {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "title": title,
        "initial_impact": initial_impact,
        "current_impact": current_impact,
        "reversible": reversible,
        "timestamp": datetime.now().isoformat(),
    })
    _save_json(OPS_FILE, ops[:200])


def get_operations() -> List[Dict]:
    return _load_json(OPS_FILE, [])


def create_project(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip())
    root = PROJECTS_ROOT / safe
    for sub in ("src", "docs", "tests", "config", "data"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(f"# {name}\n\nDelphi: Home Control project.\n")
    return root


def list_projects() -> List[Dict[str, str]]:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(PROJECTS_ROOT.iterdir()):
        if p.is_dir():
            out.append({"name": p.name, "path": str(p)})
    return out