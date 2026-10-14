"""MongoDB repository. Used only when AUTORO_DATABASE_URL is set and reachable.

If the driver is missing or the server does not answer, the caller must surface
that fact. This module never pretends a failed connection succeeded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class MongoRepository:
    adapter_name = "mongodb"

    def __init__(self, url: str, database: str) -> None:
        self.url = url
        self.database_name = database
        self._client = None
        self._db = None

    async def connect(self) -> None:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError(
                "MongoDB URL is set but pymongo is not installed. Install with: pip install -e './backend[mongo]'"
            ) from exc
        self._client = MongoClient(self.url, serverSelectionTimeoutMS=2000)
        self._client.admin.command("ping")
        self._db = self._client[self.database_name]
        self._db.documents.create_index("document_id", unique=True)
        self._db.documents.create_index("checksum")
        self._db.documents.create_index([("make", 1), ("model", 1), ("model_year", 1)])
        self._db.chunks.create_index("chunk_id", unique=True)
        self._db.chunks.create_index("document_id")
        self._db.jobs.create_index("job_id", unique=True)
        self._db.synthetic_examples.create_index("example_id", unique=True)
        self._db.gold_examples.create_index("example_id", unique=True)
        self._db.experiments.create_index("run_id", unique=True)

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _col(self, name: str):
        if self._db is None:
            raise RuntimeError("MongoDB repository is not connected")
        return self._db[name]

    async def upsert_document(self, document) -> str:
        payload = document.model_dump(mode="json")
        existing = self._col("documents").find_one({"checksum": document.checksum}, {"document_id": 1})
        if existing and existing["document_id"] != document.document_id:
            return "duplicate"
        self._col("documents").replace_one({"document_id": document.document_id}, payload, upsert=True)
        return "upserted"

    async def replace_chunks(self, document_id: str, chunks: list) -> None:
        self._col("chunks").delete_many({"document_id": document_id})
        if chunks:
            self._col("chunks").insert_many([chunk.model_dump(mode="json") for chunk in chunks])

    async def get_document(self, document_id: str):
        from app.schemas import SourceDocument

        row = self._col("documents").find_one({"document_id": document_id}, {"_id": 0})
        return None if row is None else SourceDocument.model_validate(row)

    async def list_documents(self, *, source_type: str | None = None, limit: int = 50, offset: int = 0, demo: bool | None = None):
        from app.schemas import SourceDocument

        query: dict[str, Any] = {}
        if source_type:
            query["source_type"] = source_type
        if demo is not None:
            query["demo"] = demo
        rows = self._col("documents").find(query, {"_id": 0}).sort("document_id", 1).skip(offset).limit(limit)
        return [SourceDocument.model_validate(row) for row in rows]

    async def count_documents(self) -> dict[str, int]:
        total = self._col("documents").count_documents({})
        demo_n = self._col("documents").count_documents({"demo": True})
        return {"documents": total, "demo_documents": demo_n, "non_demo_documents": total - demo_n}

    async def all_documents(self):
        return await self.list_documents(limit=100000, offset=0)

    async def all_chunks(self):
        from app.schemas import DocumentChunk

        rows = self._col("chunks").find({}, {"_id": 0}).sort([("document_id", 1), ("chunk_index", 1)])
        return [DocumentChunk.model_validate(row) for row in rows]

    async def chunks_for(self, document_id: str):
        from app.schemas import DocumentChunk

        rows = self._col("chunks").find({"document_id": document_id}, {"_id": 0}).sort("chunk_index", 1)
        return [DocumentChunk.model_validate(row) for row in rows]

    async def save_job(self, job) -> None:
        self._col("jobs").replace_one({"job_id": job.job_id}, job.model_dump(mode="json"), upsert=True)

    async def get_job(self, job_id: str):
        from app.schemas import JobRecord

        row = self._col("jobs").find_one({"job_id": job_id}, {"_id": 0})
        return None if row is None else JobRecord.model_validate(row)

    async def list_jobs(self, limit: int = 20):
        from app.schemas import JobRecord

        rows = self._col("jobs").find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
        return [JobRecord.model_validate(row) for row in rows]

    async def save_synthetic(self, example) -> None:
        self._col("synthetic_examples").replace_one(
            {"example_id": example.example_id}, example.model_dump(mode="json"), upsert=True
        )

    async def get_synthetic(self, example_id: str):
        from app.schemas import SyntheticExample

        row = self._col("synthetic_examples").find_one({"example_id": example_id}, {"_id": 0})
        return None if row is None else SyntheticExample.model_validate(row)

    async def list_synthetic(self, *, status: str | None = None, limit: int = 50, offset: int = 0):
        from app.schemas import SyntheticExample

        query = {"review_status": status} if status else {}
        rows = (
            self._col("synthetic_examples").find(query, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit)
        )
        return [SyntheticExample.model_validate(row) for row in rows]

    async def save_gold(self, example) -> None:
        self._col("gold_examples").replace_one(
            {"example_id": example.example_id}, example.model_dump(mode="json"), upsert=True
        )

    async def list_gold(self, split: str | None = None):
        from app.schemas import GoldExample

        query = {"split": split} if split else {}
        rows = self._col("gold_examples").find(query, {"_id": 0})
        return [GoldExample.model_validate(row) for row in rows]

    async def save_experiment(self, run) -> None:
        self._col("experiments").replace_one({"run_id": run.run_id}, run.model_dump(mode="json"), upsert=True)

    async def get_experiment(self, run_id: str):
        from app.schemas import ExperimentRun

        row = self._col("experiments").find_one({"run_id": run_id}, {"_id": 0})
        return None if row is None else ExperimentRun.model_validate(row)

    async def list_experiments(self, limit: int = 50):
        from app.schemas import ExperimentRun

        rows = self._col("experiments").find({}, {"_id": 0}).sort("started_at", -1).limit(limit)
        return [ExperimentRun.model_validate(row) for row in rows]

    async def add_audit(self, action: str, metadata: dict[str, Any]) -> None:
        event_id = f"aud_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        self._col("audit_events").insert_one(
            {
                "event_id": event_id,
                "action": action,
                "created_at": datetime.now(UTC).isoformat(),
                "metadata": metadata,
            }
        )

    async def counts(self) -> dict[str, Any]:
        docs = await self.count_documents()
        docs["chunks"] = self._col("chunks").count_documents({})
        docs["gold_examples"] = self._col("gold_examples").count_documents({})
        docs["synthetic_examples"] = self._col("synthetic_examples").count_documents({})
        docs["synthetic_approved"] = self._col("synthetic_examples").count_documents({"review_status": "approved"})
        docs["synthetic_pending"] = self._col("synthetic_examples").count_documents({"review_status": "pending"})
        docs["synthetic_rejected"] = self._col("synthetic_examples").count_documents({"review_status": "rejected"})
        docs["experiments"] = self._col("experiments").count_documents({})
        docs["jobs"] = self._col("jobs").count_documents({})
        return docs

    async def get_setting(self, key: str) -> str | None:
        row = self._col("app_settings").find_one({"key": key}, {"_id": 0})
        return None if row is None else row.get("value")

    async def set_setting(self, key: str, value: str) -> None:
        self._col("app_settings").replace_one({"key": key}, {"key": key, "value": value}, upsert=True)

    async def fail_interrupted_jobs(self) -> int:
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
        for name in (
            "documents",
            "chunks",
            "jobs",
            "synthetic_examples",
            "gold_examples",
            "experiments",
            "audit_events",
        ):
            self._col(name).delete_many({})
