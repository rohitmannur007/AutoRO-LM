# API

Interactive schema: `http://127.0.0.1:8000/docs` after the server starts.

Errors:

```json
{"error": {"code": "validation_error", "message": "Request validation failed", "details": []}}
```

`X-Request-ID` is set on every response.

## Examples

Health:

```bash
curl -s http://127.0.0.1:8000/api/v1/health
```

Extract:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{"text":"2018 Honda Civic. Check engine light on. DTC P0420. Replaced the catalytic converter."}'
```

Ask:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What does DTC P0420 indicate, and does the code alone prove the catalytic converter failed?"}'
```

Ingest DEMO fixtures again:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ingestion/jobs \
  -H 'Content-Type: application/json' \
  -d '{"source":"demo_fixtures"}'
```

Opt-in NHTSA complaints (network required; not part of the demo acceptance test):

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/ingestion/jobs \
  -H 'Content-Type: application/json' \
  -d '{"source":"nhtsa_complaints","make":"honda","model":"civic","model_year":2018,"max_records":25}'
```

Evaluate:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/evaluations \
  -H 'Content-Type: application/json' \
  -d '{"task":"extraction_rules"}'
```

Routes include `/api/v1/status`, `/sources`, `/sources/{id}`, `/sources/profile`, `/jobs`, `/jobs/{id}`, `/synthetic/jobs`, `/synthetic/examples`, review, rule-filter, dedupe, export, `/evaluations`, `/experiments`, and `/settings`.
