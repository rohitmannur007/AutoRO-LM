"""Benchmark the in-process demo API. This does not call Ollama or NHTSA."""

from __future__ import annotations

import os
import platform
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="autoro-bench-")
    os.environ["AUTORO_DATA_DIR"] = tmp
    os.environ["AUTORO_DATABASE_URL"] = ""
    os.environ["AUTORO_PROVIDER"] = "demo"
    os.environ["AUTORO_JOBS_INLINE"] = "1"
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    note = "2018 Honda Civic. Check engine light on. Stored DTC P0420. Replaced the catalytic converter."
    question = "What does DTC P0420 indicate, and does the code alone prove the catalytic converter failed?"
    extract_times: list[float] = []
    ask_times: list[float] = []
    errors = 0
    with TestClient(create_app()) as client:
        health = client.get("/api/v1/health")
        for _ in range(20):
            started = time.perf_counter()
            response = client.post("/api/v1/extract", json={"text": note})
            extract_times.append((time.perf_counter() - started) * 1000)
            if response.status_code != 200:
                errors += 1
            started = time.perf_counter()
            response = client.post("/api/v1/ask", json={"question": question})
            ask_times.append((time.perf_counter() - started) * 1000)
            if response.status_code != 200:
                errors += 1
        documents = client.get("/api/v1/status").json()["counts"]["documents"]
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss if platform.system() == "Darwin" else rss * 1024

    def summarize(values: list[float]) -> dict:
        ordered = sorted(values)
        return {
            "p50_ms": round(statistics.median(ordered), 2),
            "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2),
            "mean_ms": round(statistics.fmean(ordered), 2),
        }

    report = {
        "mode": "demo_in_process",
        "not": "This is not a local-model or cloud benchmark.",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "dataset_documents": documents,
        "iterations_each": 20,
        "concurrency": 1,
        "extract": summarize(extract_times),
        "ask": summarize(ask_times),
        "errors": errors,
        "max_rss_bytes": rss_bytes,
        "data_dir": str(Path(tmp)),
        "health_status": health.json()["status"],
    }
    print(report)


if __name__ == "__main__":
    main()
