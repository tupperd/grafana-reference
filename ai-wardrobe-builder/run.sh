#!/usr/bin/env bash
# Wardrobe AI launcher: sets up a venv, installs deps, preflights Ollama, runs the app.
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${OLLAMA_MODEL:-llama3.2:3b}"

# 1) Python venv + deps
if [ ! -d .venv ]; then
  echo "==> Creating virtualenv (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "==> Installing dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 2) Ollama preflight (non-fatal: app still boots, AI calls will 503 until it's up)
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo ""
  echo "!!  Ollama is not reachable at http://localhost:11434"
  echo "    Install : brew install ollama   (or https://ollama.com/download)"
  echo "    Serve   : ollama serve            (run in another terminal)"
  echo "    Model   : ollama pull ${MODEL}"
  echo ""
elif ! curl -sf http://localhost:11434/api/tags | grep -q "${MODEL%%:*}"; then
  echo "!!  Model '${MODEL}' not found in Ollama. Pull it with: ollama pull ${MODEL}"
fi

# 3) Run (config.py loads .env via python-dotenv)
echo "==> Starting Wardrobe AI on http://localhost:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
