# Security and privacy

- `.env` is gitignored. `.env.example` has placeholders only. The settings API reports whether a hosted key is present and never returns the value.
- Logs include request id, path, status, and latency. They do not include the repair note or the question body.
- Audit rows store character counts for extraction, not the note text. Synthetic examples and ingested documents are stored on purpose.
- NHTSA complaint VINs are discarded.
- Uploads are not accepted as arbitrary files. Ingestion downloads are HTTPS, host-allow-listed, size-capped, and zip members are rejected if the path is absolute or contains `..`.
- Model output is not executed. Citation quotes must be substrings of retrieved chunks.
- Request bodies are bounded by schema limits (extraction 8000 characters, question 1000, synthetic count capped).
- Expensive routes use a per-client per-minute limit (`AUTORO_RATE_LIMIT_PER_MINUTE`).
- Resetting demo data requires the exact confirmation string `RESET_DEMO_DATA`.
- Default mode does not send text to a hosted model. Selecting Ollama sends the note to the local server. Selecting the OpenAI-compatible provider sends the note to the URL you configured.
- The product is a research assistant. It is not a repair procedure and it is not a statement that a part has failed.
