#!/usr/bin/env bash
set -euo pipefail
if ! curl -fsS --max-time 2 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
  echo "Start the API first (./scripts/dev.sh), then re-run this script." >&2
  exit 1
fi
for task in extraction_rules component_classifier retrieval_comparison qa_rag synthetic_share filtered_vs_unfiltered; do
  echo "== $task =="
  curl -fsS -X POST http://127.0.0.1:8000/api/v1/evaluations \
    -H 'Content-Type: application/json' \
    -d "{\"task\":\"$task\"}"
  echo
done
