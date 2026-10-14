#!/usr/bin/env bash
# Report the local toolchain. Optional services do not fail the demo.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

say() { printf '%s\n' "$1"; }

if [[ "$(uname -m)" == "arm64" ]]; then
  say "OK    architecture: $(uname -m) (Apple Silicon or ARM64)"
else
  say "WARN  architecture: $(uname -m). This project targets Apple Silicon; other CPUs can still run the demo."
fi
say "INFO  os: $(sw_vers -productName 2>/dev/null || uname -s) $(sw_vers -productVersion 2>/dev/null || uname -r)"

if command -v python3 >/dev/null 2>&1; then
  pyv="$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
  say "OK    python3: $(command -v python3) ($pyv)"
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    say "FAIL  Python 3.11+ is required"
    fail=1
  fi
else
  say "FAIL  python3 not found"
  fail=1
fi

if [[ -x "$root/backend/.venv/bin/python" ]]; then
  say "OK    backend venv: $root/backend/.venv"
else
  say "WARN  backend venv missing. Create it with: python3 -m venv backend/.venv && backend/.venv/bin/pip install -e './backend[dev]'"
fi

if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  say "OK    node $(node -v) / npm $(npm -v)"
else
  say "FAIL  node and npm are required for the frontend"; fail=1
fi

if [[ -d "$root/frontend/node_modules" ]]; then
  say "OK    frontend dependencies installed"
else
  say "WARN  frontend/node_modules missing. Run: cd frontend && npm install"
fi

if command -v docker >/dev/null 2>&1; then
  say "OPTIONAL docker: $(docker --version 2>/dev/null | head -1). Not required for the demo."
else
  say "OPTIONAL docker not installed. MongoDB via Compose is unavailable; SQLite demo still works."
fi

if command -v ollama >/dev/null 2>&1; then
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/tmp/autoro-ollama.json 2>/dev/null; then
    say "OPTIONAL Ollama is running."
    python3 - <<'PY' || true
import json
try:
    data=json.load(open("/tmp/autoro-ollama.json"))
except Exception:
    print("OPTIONAL could not parse Ollama tags")
else:
    names=[item.get("name") for item in data.get("models",[])]
    print("OPTIONAL models:", ", ".join(names) or "none pulled")
PY
  else
    say "OPTIONAL Ollama CLI found but the server is not answering on 127.0.0.1:11434. Demo mode does not need it."
  fi
else
  say "OPTIONAL Ollama not installed. Demo mode does not need it."
fi

rm -f /tmp/autoro-ollama.json
say "INFO  default API http://127.0.0.1:8000  UI http://127.0.0.1:5173"
if [[ $fail -ne 0 ]]; then
  say "Doctor found a missing core tool."
  exit 1
fi
say "Core demo toolchain is present. Optional gaps above do not block DEMO mode."
exit 0
