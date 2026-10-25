#!/bin/bash
# Delphi Nox Dark — AI stack installer for Mac Mini M4 16GB + ExternalSSD 2TB
set -euo pipefail

NOX="/Volumes/ExternalSSD"
AI_APPS="$HOME/AI/apps"
AGENTS_DIR="$HOME/DelphiAgents"
DHC="$HOME/DelphiHomeController"

echo "=== Delphi Nox AI Stack ==="
echo "Hardware note: GLM-5.2 requires ~512GB RAM Mac Studio — SKIPPED on 16GB M4."
echo "Stack: Hermes + Ollama(MLX) + Qwen + Gemma + Fable5 prompt + Guardian CLI"

# ExternalSSD model storage (keeps internal disk free)
if [[ -d "$NOX" ]]; then
  export OLLAMA_MODELS="$NOX/AI/ollama-models"
  mkdir -p "$OLLAMA_MODELS"
  echo "OLLAMA_MODELS=$OLLAMA_MODELS"
  launchctl setenv OLLAMA_MODELS "$OLLAMA_MODELS" 2>/dev/null || true
else
  echo "WARN: ExternalSSD not mounted — models will use ~/.ollama"
fi

# Source Nox AI env if present
[[ -f "$NOX/AI/ai-env.sh" ]] && source "$NOX/AI/ai-env.sh"

# Ollama
if ! command -v ollama &>/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
ollama serve &>/dev/null &
sleep 3

# Feasible models for 16GB M4 (one heavy model at a time)
echo "Pulling Ollama models (may take a while)..."
ollama pull qwen2.5-coder:7b || true
ollama pull qwen2.5:7b-instruct || true
ollama pull gemma2:9b || true
ollama pull hermes3:8b || true

# Fable 5 — exact CL4R1T4S source per CEO spec
mkdir -p "$AGENTS_DIR/prompts"
curl -fsSL -o "$AGENTS_DIR/prompts/claude-fable-5.md" \
  "https://raw.githubusercontent.com/elder-plinius/CL4R1T4S/main/ANTHROPIC/CLAUDE-FABLE-5.md" \
  || echo "Fable 5 prompt fetch failed — retry manually"

# Qwythos-9B — register Modelfile (manual GGUF import if pull fails)
mkdir -p "$AGENTS_DIR/modelfiles"
cat > "$AGENTS_DIR/modelfiles/qwythos.Modelfile" <<'EOF'
# Import GGUF from HuggingFace empero-ai/Qwythos-9B-Claude-Mythos-5-1M-GGUF
# ollama create qwythos-9b -f ~/DelphiAgents/modelfiles/qwythos.Modelfile
FROM /Volumes/ExternalSSD/AI/models/qwythos/Qwythos-9B-Claude-Mythos-5-1M-Q4_K_M.gguf
PARAMETER temperature 0.7
SYSTEM You are Qwythos, a reasoning agent trained on Claude Mythos traces.
EOF

# MLX Python tools
"$DHC/.venv/bin/pip" install -q mlx-lm 2>/dev/null || pip3 install -q mlx-lm || true

# Clone integration repos to AI/apps
mkdir -p "$AI_APPS"
if [[ ! -d "$AI_APPS/guardian-cli" ]]; then
  git clone --depth 1 https://github.com/zakirkun/guardian-cli.git "$AI_APPS/guardian-cli" 2>/dev/null || true
fi
if [[ ! -d "$AI_APPS/timecopilot" ]]; then
  git clone --depth 1 https://github.com/TimeCopilot/timecopilot.git "$AI_APPS/timecopilot" 2>/dev/null || true
fi

# Vilix shared memory stub
mkdir -p "$DHC/data"
echo '{"memories":[]}' > "$DHC/data/vilix_memory.json"

# PhantomCloak VERSION stamp
PC="$HOME/Desktop/PhantomCloak"
if [[ -d "$PC" ]]; then
  date +"%Y.%m.%d" > "$PC/VERSION"
fi

# OpenHuman — sidecar memory harness (CTO: local Ollama provider only)
if ! [[ -d "/Applications/OpenHuman.app" ]]; then
  brew install --cask openhuman 2>/dev/null || echo "OpenHuman install skipped — run: brew install --cask openhuman"
fi
mkdir -p "$NOX/AI/openhuman-workspace" 2>/dev/null || true

echo ""
echo "=== Installed models ==="
ollama list || true
echo ""
echo "Run discovery: cd $DHC && source .venv/bin/activate && python3 -c 'from core.agent_discovery import discover; import json; print(json.dumps(discover(), indent=2))'"
echo "Done."