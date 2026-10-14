#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
echo "== backend ruff =="
(cd backend && .venv/bin/ruff check app tests scripts)
echo "== backend pytest =="
(cd backend && .venv/bin/pytest -q)
echo "== frontend =="
(cd frontend && npm run typecheck && npm run lint && npm test && npm run build)
echo "All local gates completed."
