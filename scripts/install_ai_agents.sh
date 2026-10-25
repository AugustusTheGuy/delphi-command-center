#!/bin/bash
# Delphi: Home Control — AI agent bootstrap (from Grok export turn 16)
set -e
echo "=== Delphi AI Agents Install ==="

if ! command -v ollama &>/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

ollama pull gemma2:9b 2>/dev/null || true
ollama pull qwen2.5-coder:7b 2>/dev/null || true

mkdir -p ~/DelphiAgents/prompts
curl -fsSL -o ~/DelphiAgents/prompts/claude-fable-5.md \
  https://raw.githubusercontent.com/elder-plinius/CL4R1T4S/main/ANTHROPIC/CLAUDE-FABLE-5.md \
  2>/dev/null || echo "Fable prompt fetch skipped (offline or rate limit)"

echo "Ollama models listed:"
ollama list || true
echo "Done. Wire API in Orchestrator tab (PR-08)."