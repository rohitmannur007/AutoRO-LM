# Completion report

Date: 2026-10-13, updated 2026-10-14. Machine: macOS 26.6.2, arm64 (Apple Silicon), Python 3.11.8, Node 24.11.0, npm 11.6.1. Unified memory on this Mac is 8 GB. Docker 29.3.0 and Ollama 0.33.0 (`llama3.2:1b`) were installed and were not required for the demo.

This report lists what was implemented and what was actually run. Fixture scores are not a public benchmark. The demo provider is not a language model.

## Implemented

- FastAPI `/api/v1` with health, status, extract, ask, sources, ingestion jobs, synthetic jobs, review, JSONL export, evaluations, experiments, and non-secret settings.
- Versioned Pydantic schemas and matching TypeScript types. Schema version `1.0.0`.
- SQLite repository by default. MongoDB adapter exists and falls back to SQLite with `database.fallback` when the server is unreachable. The fallback was not exercised against a live MongoDB process.
- Deterministic demo extraction and extractive QA, labeled `demo: true` and `is_llm: false`. No confidence scores.
- BM25 plus local TF-IDF cosine. Hybrid ranking is reciprocal rank fusion. A DTC in the question gets a lexical bonus so the matching fixture ranks first.
- Citations must be retrieved chunk IDs, and quotes must be substrings of those chunks. Procedure questions without a specification abstain.
- Twelve DEMO documents, eighteen gold examples, six QA labels. Holdout group `grp-holdout-camry-2019` is test-only and cannot seed synthesis.
- NHTSA complaint and recall JSON parsers, and manufacturer-communication CSV zip parsing, with HTTPS host allow-list, size cap, checksums, and zip path checks. Official schemas were read on 2026-10-13. A bounded live sample was stored in the local runtime database on 2026-10-14. See the update below. That sample is not in the zip.
- Synthetic paraphraser `deterministic_demo` (not an LLM), quality flags, review queue, split-before-synthesis refusal, JSONL export with manifest.
- Rules DTC/field extractor, TF-IDF + logistic regression for component category only, metric functions with nulls when a denominator is empty, bootstrap intervals, and error-export files from real mismatches.
- Optional Ollama and OpenAI-compatible providers. Missing Ollama returns HTTP 503. Keys stay in environment variables.
- React screens: Overview, Extraction, Diagnostic QA, Data sources, Synthetic studio, Experiments, Settings, About. Counts come from the API. Empty evaluations stay empty.
- Docs, `.env.example`, Makefile, CI workflow, doctor/dev/test/reset/eval/acceptance scripts.

## Commands run and results

| Command | Result |
| --- | --- |
| `backend/.venv/bin/ruff check app tests scripts` | Passed |
| `cd backend && .venv/bin/pytest -q` | 30 passed. One Starlette deprecation warning about `httpx` vs `httpx2`. |
| `cd frontend && npm run typecheck && npm run lint && npm test && npm run build` | Passed earlier in this session: `tsc -b`, ESLint, 3 Vitest tests, Vite production build. Vite warned that the JS chunk is over 500 kB because of the chart library. |
| `npx tsc -b` after the settings form key change | Passed (no errors). |
| `./scripts/doctor.sh` | Passed. arm64, Python 3.11 venv, Node, Docker optional, Ollama running with `llama3.2:1b`. |
| `AUTORO_API=http://127.0.0.1:8010 ./scripts/acceptance.sh` | Passed: health (SQLite, demo provider), extract, ask citing `demo-obd-p0420`, source inspect, abstention, JSONL export. |
| `backend/.venv/bin/python backend/scripts/benchmark.py` | Passed after adding the backend directory to `sys.path`. In-process demo only, 12 documents, 20 iterations, concurrency 1, 0 errors. Extract p50 1.15 ms, p95 1.59 ms. Ask p50 3.09 ms, p95 3.98 ms. Max RSS 140,574,720 bytes. Platform `macOS-26.6.2-arm64`. This is not a model benchmark. |
| `backend/.venv/bin/python backend/scripts/mlx_finetune.py` | Exit 2. `mlx-lm` is not installed. The script does not train. |
| Browser on http://127.0.0.1:5173 | Overview showed the DEMO banner, 12 documents, 12 chunks, 18 gold examples, 0 approved synthetic examples, and empty jobs/evaluations. Extraction sample note returned schema-valid JSON with evidence and unknown fields. Diagnostic QA cited `demo-obd-p0420` and the “not proof” passage. |

Port 8000 was already taken by an unrelated project. Verification used API port 8010 and `AUTORO_API_PROXY=http://127.0.0.1:8010`. That unrelated process was left running.

## Not run

- `./scripts/eval_baseline.sh` against the live API. Evaluation storage is covered by pytest (`test_evaluation_stores_measured_metrics_only`). The Experiments screen was checked in its empty state.
- A live Ollama extract or QA call. The 503 path was tested against a closed port (`127.0.0.1:9`). `llama3.2:1b` was detected by `doctor.sh` and was not used to generate answers.
- A live NHTSA ingestion job was not part of the 2026-10-13 check. A bounded live sample was stored on 2026-10-14. See the update. The manufacturer-communications zip was still not loaded into the database.
- MongoDB via Docker. The adapter and documented fallback were not connected to a running server.
- `mlx-lm` training, CUDA, or QLoRA. Those are not part of the core install and are not claimed to run here.
- `npm audit fix`. The install reported 10 audit findings. They were left unchanged.
- Git commit. The project folder is not its own git repository.

## Update 2026-10-14

Research-path code added after the first report:

- Ollama, hosted, and MLX extraction keep the model JSON. Unsupported DTCs, repairs, and parts are dropped and are not filled by the rules extractor.
- `extraction_provider` and QA evaluation call the selected provider. An unavailable provider fails the job and stores `measured: false`.
- `synthetic_share` remains the TF-IDF classifier. `synthetic_share_llm` does not copy that score.
- Training JSONL excludes the test split. A dry run does not set `trained`. A real MLX launch requires `mlx-lm` and the confirmation `TRAIN_MLX`.
- Complaint split groups are make, model, and model year. Train seeds stay off until `ENABLE_TRAIN_SEEDS`.
- Training screen, gold-label form, and substring claim checks. Claim overlap is not an entailment judgment.

Commands run on 2026-10-14:

| Command | Result |
| --- | --- |
| `ruff check app tests scripts` and `pytest -q` | Ruff passed. Pytest 39 passed, 1 Starlette warning. |
| `npx tsc -b`, `npm run lint`, `npm test`, `npm run build` | Passed. Vite again warned that the JS chunk is over 500 kB. |
| `mlx_finetune.py` | Exit 2. `mlx-lm` is not installed. No adapter was trained. |
| Live complaints API | HTTP 200. 2018 Honda Civic returned `count` 596; 50 were parsed and stored. 2019 Toyota Camry returned `count` 397; 20 stored. 2020 Ford F-150 returned `count` 48; 20 stored. |
| Live recalls API | 2018 Honda Civic, 6 recall summaries parsed and stored as `reference`, synthetic seed false. |
| Split assignment, seed 42 | `honda\|civic\|2018` train (50), `ford\|f-150\|2020` validation (20), `toyota\|camry\|2019` test (20). `allow_synthetic_seed` stayed false. No VIN from the payload was present in the stored text. |
| Local database after that load | 108 documents: 12 DEMO, 96 non-demo. This SQLite file is under `backend/data/runtime` and is excluded from the zip. |

These complaint counts are a capped sample, not the full NHTSA corpus, and they are consumer narratives rather than confirmed repair orders. No gold labels were created for them. No fine-tuned LLM metric was measured.

## Known limitations

- No MLX adapter has been trained. This Mac has 8 GB unified memory, and `mlx-lm` is not installed. The launcher exits 2 instead of reporting a trained model.
- The live NHTSA sample is capped and is not a gold-labeled training set. The 2019 Camry group is test and cannot seed synthetic examples.
- Demo extraction is transparent rules. Unseen wording will miss fields rather than invent them.
- Retrieval embeddings are TF-IDF, not a neural embedding model.
- Synthetic “generation” in demo mode is a deterministic paraphraser. It refuses test-split seeds. It is labeled as not a language model.
- A DTC is not treated as proof that a component failed.
- All diagnosis text is informational. Repairs need the manufacturer’s service information and a qualified technician.
