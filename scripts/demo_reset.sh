#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
# Calls the running API if it is up. Otherwise prints the equivalent request.
if curl -fsS --max-time 2 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
  curl -fsS -X POST http://127.0.0.1:8000/api/v1/settings/reset-demo \
    -H 'Content-Type: application/json' \
    -d '{"confirm":"RESET_DEMO_DATA"}'
  echo
else
  echo "API is not running on port 8000."
  echo "Start it, then: curl -X POST http://127.0.0.1:8000/api/v1/settings/reset-demo -H 'Content-Type: application/json' -d '{\"confirm\":\"RESET_DEMO_DATA\"}'"
  echo "Or delete $root/backend/data/runtime and restart; fixtures reload when the database is empty."
  exit 1
fi
