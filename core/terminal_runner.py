"""Sandboxed terminal command runner for project management (PR-03)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

ALLOWED_PREFIXES = (
    "ls", "pwd", "echo", "cat", "head", "tail", "git status", "git log", "git diff",
    "python --version", "pip list", "streamlit --version", "docker ps", "docker compose ps",
    "ollama list", "brew list", "which",
)


@dataclass
class RunResult:
    command: str
    stdout: str
    stderr: str
    returncode: int
    allowed: bool


def is_allowed(command: str) -> bool:
    cmd = command.strip()
    if not cmd:
        return False
    return any(cmd == p or cmd.startswith(p + " ") for p in ALLOWED_PREFIXES)


def run(command: str, cwd: str | None = None, timeout: int = 30) -> RunResult:
    if not is_allowed(command):
        return RunResult(command, "", "Command not in allowlist", -1, False)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return RunResult(command, proc.stdout, proc.stderr, proc.returncode, True)
    except subprocess.TimeoutExpired:
        return RunResult(command, "", "Timeout", -1, True)