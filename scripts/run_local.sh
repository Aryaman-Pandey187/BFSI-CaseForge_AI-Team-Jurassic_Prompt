#!/usr/bin/env bash
# =============================================================================
# Run CaseForge AI locally without Docker.
#   ./scripts/run_local.sh          # build UI once, serve everything on http://localhost:8080
#   ./scripts/run_local.sh --dev    # backend on :8080 + Vite hot-reload UI on :5173
# Defaults to the offline mode (mock LLM, in-memory data); edit .env for real GCP.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
[[ -f .env ]] || cp .env.example .env

if [[ ! -d backend/.venv ]]; then
  python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install -q -r backend/requirements.txt

(cd frontend && [[ -d node_modules ]] || npm install --no-audit --no-fund)

if [[ "${1:-}" == "--dev" ]]; then
  (cd backend && ../backend/.venv/bin/uvicorn app.main:app --reload --port 8080) &
  BACK=$!
  trap 'kill $BACK' EXIT
  cd frontend && npm run dev
else
  (cd frontend && npm run build)
  cd backend && STATIC_DIR="$ROOT/frontend/dist" .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
fi
