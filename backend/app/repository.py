"""SQLite repository. The active adapter is always reported explicitly."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  document_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_group TEXT,
  split TEXT,
  make TEXT,
  model TEXT,
  model_year INTEGER,
  checksum TEXT NOT NULL,
  demo INTEGER NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS synthetic_examples (
  example_id TEXT PRIMARY KEY,
  source_group TEXT,
  review_status TEXT,
  created_at TEXT,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gold_examples (
  example_id TEXT PRIMARY KEY,
  split TEXT,
  source_group TEXT,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
  run_id TEXT PRIMARY KEY,
  task TEXT,
  status TEXT,
  created_at TEXT,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(source_type);
CREATE INDEX IF NOT EXISTS idx_documents_vehicle ON documents(make, model, model_year);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_synthetic_status ON synthetic_examples(review_status);
"""


def _dumps(model_or_dict) -> str:
    if hasattr(model_or_dict, "model_dump"):
        return json.dumps(model_or_dict.model_dump(mode="json"))
    return json.dumps(model_or_dict)


class SQLiteRepository:
    adapter_name = "sqlite"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA foreign_keys=ON;")
        await self._db.executescript(SCHEMA)
        await self._db.execute("PRAGMA user_version=1;")
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("repository is not connected")
        return self._db

    async def upsert_document(self, document) -> str:
        existing = await self.db.execute(
            "SELECT document_id FROM documents WHERE checksum = ?",
            (document.checksum,),
        )
        row = await existing.fetchone()
        if row and row["document_id"] != document.document_id:
            return "duplicate"
        await self.db.execute(
            """
            INSERT INTO documents (document_id, source_type, source_group, split, make, model, model_year, checksum, demo, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
              source_type=excluded.source_type,
              source_group=excluded.source_group,
              split=excluded.split,
              make=excluded.make,
              model=excluded.model,
              model_year=excluded.model_year,
              checksum=excluded.checksum,
              demo=excluded.demo,
              payload=excluded.payload
            """,
            (
                document.document_id,
                document.source_type,
                document.source_group,
                document.split,
                document.make,
                document.model,
                document.model_year,
                document.checksum,
                1 if document.demo else 0,
                _dumps(document),
            ),
        )
        await self.db.commit()
        return "upserted"

    async def replace_chunks(self, document_id: str, chunks: list) -> None:
        await self.db.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        for chunk in chunks:
            await self.db.execute(
                "INSERT INTO chunks (chunk_id, document_id, chunk_index, payload) VALUES (?, ?, ?, ?)",
                (chunk.chunk_id, document_id, chunk.chunk_index, _dumps(chunk)),
            )
        await self.db.commit()

    async def get_document(self, document_id: str):
        from app.schemas import SourceDocument

        cursor = await self.db.execute("SELECT payload FROM documents WHERE document_id = ?", (document_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return SourceDocument.model_validate_json(row["payload"])

    async def list_documents(self, *, source_type: str | None = None, limit: int = 50, offset: int = 0, demo: bool | None = None):
        from app.schemas import SourceDocument

        clauses = []
        params: list[Any] = []
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        if demo is not None:
            clauses.append("demo = ?")
            params.append(1 if demo else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = await self.db.execute(
            f"SELECT payload FROM documents {where} ORDER BY document_id LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        rows = await cursor.fetchall()
        return [SourceDocument.model_validate_json(row["payload"]) for row in rows]

    async def count_documents(self) -> dict[str, int]:
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS n, SUM(demo) AS demo_n FROM documents"
        )
        row = await cursor.fetchone()
        total = int(row["n"] or 0)
        demo_n = int(row["demo_n"] or 0)
        return {"documents": total, "demo_documents": demo_n, "non_demo_documents": total - demo_n}

    async def all_documents(self):
        return await self.list_documents(limit=100000, offset=0)

    async def all_chunks(self):
        from app.schemas import DocumentChunk

        cursor = await self.db.execute("SELECT payload FROM chunks ORDER BY document_id, chunk_index")
        rows = await cursor.fetchall()
        return [DocumentChunk.model_validate_json(row["payload"]) for row in rows]

    async def chunks_for(self, document_id: str):
        from app.schemas import DocumentChunk

        cursor = await self.db.execute(
            "SELECT payload FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (document_id,),
        )
        rows = await cursor.fetchall()
        return [DocumentChunk.model_validate_json(row["payload"]) for row in rows]

    async def save_job(self, job) -> None:
        await self.db.execute(
            """
            INSERT INTO jobs (job_id, job_type, status, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
              job_type=excluded.job_type,
              status=excluded.status,
              payload=excluded.payload
            """,
            (job.job_id, job.job_type, job.status, job.created_at.isoformat(), _dumps(job)),
        )
        await self.db.commit()

    async def get_job(self, job_id: str):
        from app.schemas import JobRecord

        cursor = await self.db.execute("SELECT payload FROM jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return JobRecord.model_validate_json(row["payload"])

    async def list_jobs(self, limit: int = 20):
        from app.schemas import JobRecord

        cursor = await self.db.execute(
            "SELECT payload FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [JobRecord.model_validate_json(row["payload"]) for row in rows]

    async def save_synthetic(self, example) -> None:
        await self.db.execute(
            """
            INSERT INTO synthetic_examples (example_id, source_group, review_status, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(example_id) DO UPDATE SET
              review_status=excluded.review_status,
              payload=excluded.payload
            """,
            (
                example.example_id,
                example.source_group,
                example.review_status,
                example.created_at.isoformat(),
                _dumps(example),
            ),
        )
        await self.db.commit()

    async def get_synthetic(self, example_id: str):
        from app.schemas import SyntheticExample

        cursor = await self.db.execute(
            "SELECT payload FROM synthetic_examples WHERE example_id = ?",
            (example_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return SyntheticExample.model_validate_json(row["payload"])

    async def list_synthetic(self, *, status: str | None = None, limit: int = 50, offset: int = 0):
        from app.schemas import SyntheticExample

        if status:
            cursor = await self.db.execute(
                "SELECT payload FROM synthetic_examples WHERE review_status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cursor = await self.db.execute(
                "SELECT payload FROM synthetic_examples ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
        return [SyntheticExample.model_validate_json(row["payload"]) for row in rows]

    async def save_gold(self, example) -> None:
        await self.db.execute(
            """
            INSERT INTO gold_examples (example_id, split, source_group, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(example_id) DO UPDATE SET
              split=excluded.split,
              source_group=excluded.source_group,
              payload=excluded.payload
            """,
            (example.example_id, example.split, example.source_group, _dumps(example)),
        )
        await self.db.commit()

    async def list_gold(self, split: str | None = None):
        from app.schemas import GoldExample

        if split:
            cursor = await self.db.execute("SELECT payload FROM gold_examples WHERE split = ?", (split,))
        else:
            cursor = await self.db.execute("SELECT payload FROM gold_examples")
        rows = await cursor.fetchall()
        return [GoldExample.model_validate_json(row["payload"]) for row in rows]

    async def save_experiment(self, run) -> None:
        created = (run.started_at or datetime.now(UTC)).isoformat()
        await self.db.execute(
            """
            INSERT INTO experiments (run_id, task, status, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              task=excluded.task,
              status=excluded.status,
              payload=excluded.payload
            """,
            (run.run_id, run.task, run.status, created, _dumps(run)),
        )
        await self.db.commit()

    async def get_experiment(self, run_id: str):
        from app.schemas import ExperimentRun

        cursor = await self.db.execute("SELECT payload FROM experiments WHERE run_id = ?", (run_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return ExperimentRun.model_validate_json(row["payload"])

    async def list_experiments(self, limit: int = 50):
        from app.schemas import ExperimentRun

        cursor = await self.db.execute(
            "SELECT payload FROM experiments ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [ExperimentRun.model_validate_json(row["payload"]) for row in rows]

    async def add_audit(self, action: str, metadata: dict[str, Any]) -> None:
        event_id = f"aud_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        payload = {
            "event_id": event_id,
            "action": action,
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": metadata,
        }
        await self.db.execute(
            "INSERT INTO audit_events (event_id, created_at, payload) VALUES (?, ?, ?)",
            (event_id, payload["created_at"], json.dumps(payload)),
        )
        await self.db.commit()

    async def counts(self) -> dict[str, Any]:
        docs = await self.count_documents()
        async def scalar(query: str) -> int:
            cursor = await self.db.execute(query)
            row = await cursor.fetchone()
            return int(list(row)[0] or 0)

        docs["chunks"] = await scalar("SELECT COUNT(*) FROM chunks")
        docs["gold_examples"] = await scalar("SELECT COUNT(*) FROM gold_examples")
        docs["synthetic_examples"] = await scalar("SELECT COUNT(*) FROM synthetic_examples")
        docs["synthetic_approved"] = await scalar(
            "SELECT COUNT(*) FROM synthetic_examples WHERE review_status = 'approved'"
        )
        docs["synthetic_pending"] = await scalar(
            "SELECT COUNT(*) FROM synthetic_examples WHERE review_status = 'pending'"
        )
        docs["synthetic_rejected"] = await scalar(
            "SELECT COUNT(*) FROM synthetic_examples WHERE review_status = 'rejected'"
        )
        docs["experiments"] = await scalar("SELECT COUNT(*) FROM experiments")
        docs["jobs"] = await scalar("SELECT COUNT(*) FROM jobs")
        return docs

    async def get_setting(self, key: str) -> str | None:
        cursor = await self.db.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return None if row is None else row["value"]

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self.db.commit()

    async def fail_interrupted_jobs(self) -> int:
        from datetime import UTC, datetime

        changed = 0
        for job in await self.list_jobs(500):
            if job.status not in {"queued", "running"}:
                continue
            job.status = "failed"
            job.finished_at = datetime.now(UTC)
            job.errors.append("Interrupted by process restart. Start the job again.")
            await self.save_job(job)
            changed += 1
        return changed

    async def clear_all(self) -> None:
        for table in (
            "documents",
            "chunks",
            "jobs",
            "synthetic_examples",
            "gold_examples",
            "experiments",
            "audit_events",
        ):
            await self.db.execute(f"DELETE FROM {table}")
        await self.db.commit()
