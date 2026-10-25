#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=== Delphi: Home Control — Setup ==="
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data/profiles data/projects data/logs data/uploads
chmod 700 data

if [ ! -f data/.auth_secret ]; then
  python3 -c "from core.auth import ensure_default_user; ensure_default_user()"
  echo "Local session ready. No password is set."
fi

echo ""
echo "Launch: source .venv/bin/activate && streamlit run delphi_command_center.py --server.port 8501"
echo "Access: http://localhost:8501 (use Tailscale for remote)"