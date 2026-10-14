#!/usr/bin/env bash
# Offline acceptance against a running demo API. Does not call NHTSA or Ollama.
set -euo pipefail
base="${AUTORO_API:-http://127.0.0.1:8000}"
tmpdir="$(mktemp -d)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT

echo "health"
curl -fsS "$base/api/v1/health" | tee "$tmpdir/health.json" >/dev/null
python3 - "$tmpdir/health.json" <<'PY'
import json, sys
body=json.load(open(sys.argv[1]))
assert body["status"] in {"ok", "degraded"}
assert body["secrets_exposed"] is False
assert body["database"]["active_adapter"]
print("health ok", body["database"]["active_adapter"], "demo_provider", body["demo_provider"])
PY

echo "extract"
curl -fsS -X POST "$base/api/v1/extract" -H 'Content-Type: application/json' \
  -d '{"text":"2018 Honda Civic. Check engine light on. Stored DTC P0420. Customer reports a rotten egg smell at idle. Replaced the catalytic converter."}' \
  | tee "$tmpdir/extract.json" >/dev/null
python3 - "$tmpdir/extract.json" <<'PY'
import json, sys
body=json.load(open(sys.argv[1]))
assert body["schema_valid"] is True
assert body["dtc_codes"]==["P0420"]
assert body["component"]=="catalytic converter"
assert body["demo"] is True
assert "confidence" not in body
print("extract", body["extraction_id"])
PY

echo "ask"
curl -fsS -X POST "$base/api/v1/ask" -H 'Content-Type: application/json' \
  -d '{"question":"What does DTC P0420 indicate, and does the code alone prove the catalytic converter failed?"}' \
  | tee "$tmpdir/ask.json" >/dev/null
doc="$(python3 - "$tmpdir/ask.json" <<'PY'
import json, sys
body=json.load(open(sys.argv[1]))
assert body["abstained"] is False
assert body["citations"]
cid=body["citations"][0]["chunk_id"]
assert cid in body["retrieved_chunk_ids"]
assert "not proof" in body["answer"].lower()
assert body["citations"][0]["document_id"] == "demo-obd-p0420"
print(body["citations"][0]["document_id"])
PY
)"
echo "ask cited $doc"
echo "source $doc"
curl -fsS "$base/api/v1/sources/$doc" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["document"]["demo"] is True; print(d["document"]["source_name"])'

echo "abstain"
curl -fsS -X POST "$base/api/v1/ask" -H 'Content-Type: application/json' \
  -d '{"question":"What is the cylinder head bolt torque specification for a 2019 Toyota Camry?"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["abstained"] is True; assert "ft-lb" not in d["answer"].lower(); print("abstained")'

echo "export"
curl -fsS "$base/api/v1/synthetic/examples/export" | head -c 200 >/dev/null
echo
echo "acceptance passed"
