# Auto Royal M (AutoRO-LM)

AutoRO-LM is a local research prototype for automotive repair text. It turns a noisy note into schema-checked JSON, and it answers questions only when a retrieved passage supports the answer. The shipped corpus is a labeled **DEMO** fixture pack. It is not a dump of NHTSA complaints and it is not connected to any private repair platform.

The default path runs on an Apple Silicon Mac with Python and Node. It does not need an API key, a GPU, Docker, MongoDB, or a downloaded language model.

## What you can do

- Extract symptoms, DTCs, components, and repair actions with evidence quotes. Missing fields stay null. A DTC does not fill a failed part.
- Ask a question and read citations that point at the retrieved chunk. Unsupported questions abstain.
- Inspect source records, provenance, and a profile computed from what is actually stored.
- Paraphrase train-split seeds with a deterministic teacher (not an LLM). Ollama is optional and fails closed.
- Run rule, TF-IDF classifier, retrieval, and QA evaluations. Charts render only from stored runs.

## Layout

- `backend/app` FastAPI service, schemas, retrieval, providers, ingestion, metrics
- `backend/data/demo` hand-authored fixtures
- `frontend` React, TypeScript, Vite, Tailwind
- `docs` architecture, data sources, annotation, experiments, Mac setup, privacy
- `scripts` doctor, dev, test, demo reset, acceptance

## Quick start (Mac, Apple Silicon)

```bash
cd "/path/to/Auto Royal M"
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -U pip
python -m pip install -e "./backend[dev]"
cd frontend && npm install && cd ..
chmod +x scripts/*.sh
./scripts/doctor.sh
./scripts/dev.sh
```

Open http://127.0.0.1:5173. API docs: http://127.0.0.1:8000/docs.

Details, optional MongoDB, Ollama, and MLX: [docs/MAC_M2_SETUP.md](docs/MAC_M2_SETUP.md).

## Demo versus real data

DEMO fixtures load automatically into SQLite at `backend/data/runtime/`. Reload them with:

```bash
./scripts/demo_reset.sh
```

NHTSA complaints and recalls use the public JSON API. Manufacturer communications use the official CSV zip because the JSON communications URLs that were tried on 2026-10-13 returned HTTP 403. Start those jobs from Data sources. They are not required for the demo. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Tests

```bash
./scripts/test.sh
```

With the API already running:

```bash
./scripts/acceptance.sh
```

In-process demo latency sample (not a model benchmark):

```bash
backend/.venv/bin/python backend/scripts/benchmark.py
```

## Safety

Informational only. Confirm repairs, especially brakes, steering, airbags, fuel, and high-voltage systems, with the manufacturer’s service information and a qualified technician. A diagnostic trouble code alone is not proof a component failed.

## Limitations

- The demo provider is rules plus extractive quotes. It will not match a technician on unseen wording.
- Fixture evaluation numbers are not a public benchmark.
- Neural embeddings and MLX fine-tunes are not installed by the core setup. `backend/scripts/mlx_finetune.py` explains the optional Apple Silicon path and does not pretend CUDA QLoRA works on an M2.
- Hosted models run only if you set `AUTORO_OPENAI_COMPAT_*` in an untracked `.env`.
