# AutoRO-LM implementation checklist

Environment inspected on 2026-10-13:

- macOS 26.6.2, Apple Silicon (`arm64`)
- Python 3.11.8 (pyenv), Node 24.11.0, npm 11.6.1
- Docker 29.3.0 present; not required for the demo
- Ollama 0.33.0 present with `llama3.2:1b`; demo mode does not call it
- Repository contained only `MASTER_BUILD_PROMPT.txt`

Phases:

1. Checklist, toolchain notes, and project skeleton.
2. Versioned Pydantic schemas, settings, and provider interfaces.
3. Deterministic demo extraction, grounded QA, lexical/TF-IDF retrieval, SQLite persistence, health, and tests.
4. React/TypeScript screens wired to the API.
5. Opt-in NHTSA complaints, recalls, and manufacturer-communications adapters with provenance and background jobs.
6. Rules baseline, TF-IDF + logistic regression baseline, splits, metrics, and stored experiment runs.
7. Deterministic synthetic paraphraser, quality filters, review, and Ollama teacher only when configured.
8. Optional Ollama inference and a documented MLX path that does not pretend to train.
9. Hardening, docs, CI, doctor/dev/test scripts.
10. Run tests, frontend build, doctor, and acceptance flow.
11. Completion report from commands actually run.
12. `Auto Royal M.zip` excluding virtualenvs, `node_modules`, caches, secrets, and weights.

Defaults chosen for this machine:

- Persistence: SQLite file under `backend/data/runtime/` unless `AUTORO_DATABASE_URL` is a MongoDB URL.
- Model provider: `demo` (deterministic rules). Not an LLM.
- Vector index: local TF-IDF cosine. No downloaded embedding model.
- Hybrid rank: reciprocal rank fusion of BM25 and TF-IDF when both indexes exist.
