#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
if [[ ! -x backend/.venv/bin/uvicorn ]]; then
  echo "Missing backend/.venv. See docs/MAC_M2_SETUP.md" >&2
  exit 1
fi
if [[ ! -d frontend/node_modules ]]; then
  echo "Missing frontend/node_modules. Run npm install in frontend/." >&2
  exit 1
fi
cleanup() {
  if [[ -n "${BACK_PID:-}" ]]; then kill "$BACK_PID" 2>/dev/null || true; fi
  if [[ -n "${FRONT_PID:-}" ]]; then kill "$FRONT_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
(cd backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACK_PID=$!
(cd frontend && exec npm run dev -- --host 127.0.0.1 --port 5173) &
FRONT_PID=$!
echo "API  http://127.0.0.1:8000/docs"
echo "UI   http://127.0.0.1:5173"
wait
