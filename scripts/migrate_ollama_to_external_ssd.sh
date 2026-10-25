#!/bin/bash
# Migrate Ollama model blobs from ~/.ollama/models to ExternalSSD (idempotent).
set -euo pipefail

NOX="/Volumes/ExternalSSD/AI/ollama-models"
SRC="$HOME/.ollama/models"

if [[ ! -d "/Volumes/ExternalSSD" ]]; then
  echo "ERROR: ExternalSSD not mounted at /Volumes/ExternalSSD"
  exit 1
fi

mkdir -p "$NOX"

if pgrep -f "ollama serve" >/dev/null; then
  echo "Stopping Ollama..."
  killall Ollama 2>/dev/null || pkill -f "ollama serve" || true
  sleep 3
fi

for sub in blobs manifests; do
  if [[ -d "$SRC/$sub" ]] && [[ "$(ls -A "$SRC/$sub" 2>/dev/null)" ]]; then
    echo "Moving $sub to ExternalSSD..."
    mkdir -p "$NOX/$sub"
    rsync -a --remove-source-files "$SRC/$sub/" "$NOX/$sub/"
    rmdir "$SRC/$sub" 2>/dev/null || true
  fi
done

launchctl setenv OLLAMA_MODELS "$NOX"
grep -q 'OLLAMA_MODELS=' "$HOME/.zshrc" 2>/dev/null || {
  echo 'export OLLAMA_MODELS="/Volumes/ExternalSSD/AI/ollama-models"' >> "$HOME/.zshrc"
}

echo "OLLAMA_MODELS=$NOX"
du -sh "$NOX"
open -a Ollama 2>/dev/null || true
sleep 4
OLLAMA_MODELS="$NOX" ollama list