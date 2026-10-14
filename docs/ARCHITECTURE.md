# Architecture

AutoRO-LM is a local research prototype. The browser never calls a model provider directly.

```text
React UI  --HTTP /api/v1-->  FastAPI
                              |-- Provider interface
                              |     demo rules + extractive quotes
                              |     Ollama (optional)
                              |     OpenAI-compatible HTTP (optional, no SDK)
                              |-- RetrievalIndex
                              |     BM25 lexical (always)
                              |     TF-IDF cosine (scikit-learn, not a neural embedding)
                              |     hybrid = reciprocal rank fusion, k=60
                              |-- Repository
                              |     SQLite by default
                              |     MongoDB only when AUTORO_DATABASE_URL connects
                              |-- Job runner
                                    inline in tests, asyncio tasks in the server
```

## Request paths

Extraction normalizes whitespace, runs the active provider, and validates evidence quotes against the note. The demo provider is a rule extractor. It does not return a confidence score.

Diagnostic QA retrieves chunks, then asks the provider to answer only from those chunks. Citations whose chunk id was not retrieved, or whose quote is not a substring of that chunk, are discarded and the response abstains.

Ingestion and evaluation jobs are stored as `queued`, `running`, `completed`, or `failed`. A failed external download does not insert placeholder documents.

## Persistence

Documents, chunks, gold examples, synthetic examples, jobs, and experiment runs are JSON payloads plus indexed columns. Raw NHTSA downloads, when the user opts in, stay as parsed documents with provenance. Large zip bytes are not copied into MongoDB; the SQLite/Mongo row stores text and metadata.

`PRAGMA user_version` is 1. A future schema change should bump that value and migrate explicitly.

## Splits

Source groups are assigned before synthesis. Only `train` documents with `allow_synthetic_seed` can seed paraphrases. The 2019 Camry fixture group is a holdout and is rejected as a seed.

## What is not in the core loop

MLX fine-tuning, Ollama generation, and NHTSA downloads are optional. If they are unavailable the API returns a configuration or job error instead of a fabricated result.
