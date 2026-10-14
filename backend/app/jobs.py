"""Durable job records with an inline mode for tests and a background mode for the server."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import httpx

from app.bootstrap import load_demo_fixtures, rebuild_index
from app.evaluation import (
    evaluate_classifier,
    evaluate_extraction_rules,
    evaluate_filtered_vs_unfiltered,
    evaluate_provider_extraction,
    evaluate_qa,
    evaluate_retrieval,
    evaluate_synthetic_share,
    evaluate_synthetic_share_llm,
    write_error_export,
)
from app.ingestion import (
    NHTSA_COMPLAINTS_URL,
    NHTSA_MFR_CSV_URL,
    NHTSA_RECALLS_URL,
    chunks_for_document,
    download_bytes,
    fetch_json,
    parse_complaint_payload,
    parse_mfr_csv,
    parse_recall_payload,
    safe_zip_csv,
)
from app.schemas import IngestionJobRequest, JobRecord, SyntheticJobRequest
from app.synthetic import apply_rule_filter, generate_from_document, generate_with_teacher

logger = logging.getLogger("autoro.jobs")


def new_job(job_type: str, action: str, metadata: dict | None = None) -> JobRecord:
    return JobRecord(
        job_id=f"job_{uuid.uuid4().hex[:12]}",
        job_type=job_type,
        action=action,
        status="queued",
        created_at=datetime.now(UTC),
        metadata=metadata or {},
    )


class JobRunner:
    def __init__(self, settings, repo, state: dict) -> None:
        self.settings = settings
        self.repo = repo
        self.state = state
        self._tasks: set[asyncio.Task] = set()

    async def submit(self, job: JobRecord, worker) -> JobRecord:
        await self.repo.save_job(job)
        if self.settings.jobs_inline:
            await self._execute(job.job_id, worker)
            return await self.repo.get_job(job.job_id)
        task = asyncio.create_task(self._execute(job.job_id, worker))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _execute(self, job_id: str, worker) -> None:
        job = await self.repo.get_job(job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.logs.append("started")
        await self.repo.save_job(job)
        try:
            await worker(job)
            job = await self.repo.get_job(job_id)
            job.status = "completed"
            job.finished_at = datetime.now(UTC)
            job.logs.append("completed")
            await self.repo.save_job(job)
        except Exception as exc:
            logger.exception("job failed", extra={"path": job_id})
            job = await self.repo.get_job(job_id)
            job.status = "failed"
            job.finished_at = datetime.now(UTC)
            job.errors.append(f"{exc.__class__.__name__}: {exc}")
            job.logs.append("failed")
            await self.repo.save_job(job)

    async def run_ingestion(self, job: JobRecord, request: IngestionJobRequest) -> None:
        if request.source == "demo_fixtures":
            result = await load_demo_fixtures(self.repo, self.settings.demo_dir, force=True)
            self.state["index"] = await rebuild_index(self.repo)
            job.counts = {"documents": int(result.get("documents", 0)), "gold": int(result.get("gold", 0))}
            job.metadata["result"] = result
            await self.repo.save_job(job)
            return
        if request.source in {"nhtsa_complaints", "nhtsa_recalls"}:
            if not request.make or not request.model or not request.model_year:
                raise ValueError("make, model, and model_year are required for NHTSA vehicle queries")
            url = NHTSA_COMPLAINTS_URL if request.source == "nhtsa_complaints" else NHTSA_RECALLS_URL
            params = {"make": request.make, "model": request.model, "modelYear": request.model_year}
            payload = await _get_json_with_retry(url, params, self.settings.nhtsa_timeout_seconds)
            now = datetime.now(UTC)
            if request.source == "nhtsa_complaints":
                docs = parse_complaint_payload(payload, retrieved_at=now, max_records=request.max_records)
            else:
                docs = parse_recall_payload(payload, retrieved_at=now, max_records=request.max_records)
        else:
            url = request.url or NHTSA_MFR_CSV_URL
            async with httpx.AsyncClient(timeout=self.settings.nhtsa_timeout_seconds, follow_redirects=True) as client:
                data, digest = await download_bytes(client, url, max_bytes=self.settings.download_max_bytes)
            text = safe_zip_csv(data, max_uncompressed=self.settings.download_max_bytes)
            docs = parse_mfr_csv(text, retrieved_at=datetime.now(UTC), source_url=url, max_records=request.max_records)
            job.metadata["sha256"] = digest
        inserted = duplicates = 0
        for document in docs:
            outcome = await self.repo.upsert_document(document)
            if outcome == "duplicate":
                duplicates += 1
                continue
            await self.repo.replace_chunks(document.document_id, chunks_for_document(document))
            inserted += 1
        self.state["index"] = await rebuild_index(self.repo)
        job.counts = {"fetched": len(docs), "inserted": inserted, "duplicates": duplicates}
        await self.repo.save_job(job)

    async def run_synthetic(self, job: JobRecord, request: SyntheticJobRequest) -> None:
        if request.teacher == "deterministic_demo" and self.settings.teacher_provider == "none":
            raise RuntimeError("Synthetic generation is disabled. Set AUTORO_TEACHER_PROVIDER.")
        ids = list(request.seed_document_ids)
        if not ids:
            docs = await self.repo.list_documents(limit=1000)
            ids = [doc.document_id for doc in docs if doc.allow_synthetic_seed and doc.split == "train"]
        created = 0
        rejected = 0
        errors = []
        remaining = min(request.count, self.settings.max_synthetic_count)
        for document_id in ids:
            if remaining <= 0:
                break
            document = await self.repo.get_document(document_id)
            if document is None:
                errors.append(f"missing seed {document_id}")
                continue
            try:
                if request.teacher == "ollama":
                    example = await generate_with_teacher(document, "ollama", self.settings, request.variations[0])
                    batch = [example]
                else:
                    batch = generate_from_document(
                        document,
                        request.variations,
                        teacher="deterministic_demo",
                        limit=remaining,
                    )
            except Exception as exc:
                errors.append(f"{document_id}: {exc}")
                continue
            for example in batch:
                if remaining <= 0:
                    break
                await self.repo.save_synthetic(example)
                created += 1
                remaining -= 1
                if example.review_status == "rejected":
                    rejected += 1
        job.counts = {"created": created, "auto_rejected": rejected}
        job.errors.extend(errors)
        job.metadata["teacher"] = request.teacher
        job.metadata["is_llm"] = request.teacher == "ollama"
        job.metadata["demo_generator"] = request.teacher == "deterministic_demo"
        await self.repo.save_job(job)
        if created == 0:
            detail = "; ".join(errors) if errors else "No eligible train-split seed documents."
            raise RuntimeError(detail)

    async def run_evaluation(self, job: JobRecord, task: str) -> None:
        index = self.state["index"]
        labels = self.state.get("qa_labels") or []
        if task == "extraction_rules":
            run = await evaluate_extraction_rules(self.repo)
        elif task == "component_classifier":
            run = await evaluate_classifier(self.repo)
        elif task == "retrieval_comparison":
            run = await evaluate_retrieval(self.repo, index, labels)
        elif task == "qa_rag":
            run = await evaluate_qa(self.repo, index, labels, self.settings)
        elif task == "synthetic_share":
            run = await evaluate_synthetic_share(self.repo)
        elif task == "synthetic_share_llm":
            run = await evaluate_synthetic_share_llm(self.repo, self.settings)
        elif task == "extraction_provider":
            run = await evaluate_provider_extraction(self.repo, self.settings)
        elif task == "filtered_vs_unfiltered":
            run = await evaluate_filtered_vs_unfiltered(self.repo)
        else:
            raise ValueError(f"unknown evaluation task {task}")
        artifact = write_error_export(self.settings.data_dir / "artifacts", run)
        if artifact:
            run.artifact_paths.append(artifact)
        await self.repo.save_experiment(run)
        job.metadata["run_id"] = run.run_id
        job.metadata["task"] = task
        job.metadata["evaluation_status"] = run.status
        job.metadata["model_provider"] = run.model_provider
        job.counts = {"metrics": 1}
        await self.repo.save_job(job)
        if run.status == "unavailable" and run.metrics.get("measured") is False:
            raise RuntimeError(str(run.metrics.get("reason") or "evaluation unavailable"))

    async def run_training(self, job: JobRecord, request) -> None:
        from app.mlx_train import DEFAULTS, launch_lora
        from app.training_data import build_training_dataset

        if not request.dry_run and request.confirm != "TRAIN_MLX":
            raise RuntimeError("Confirmation text must be TRAIN_MLX before a real fine-tune starts.")
        share_label = str(int(round(request.mixture_share * 100)))
        dest = self.settings.data_dir / "training" / f"share-{share_label}"
        manifest = await build_training_dataset(self.repo, dest, mixture_share=request.mixture_share)
        if manifest["train_count"] < 1:
            raise RuntimeError(manifest.get("mixture_reason") or "No eligible train rows.")
        config = {
            **DEFAULTS,
            "iters": request.iters or min(self.settings.mlx_iters, 200),
            "lora_layers": self.settings.mlx_lora_layers,
            "lora_rank": self.settings.mlx_lora_rank,
            "learning_rate": self.settings.mlx_learning_rate,
            "batch_size": self.settings.mlx_batch_size,
            "seed": self.settings.mlx_seed,
        }
        model = request.model or self.settings.mlx_model
        record = launch_lora(
            model=model,
            data_dir=dest,
            adapter_path=self.settings.resolved_adapter_dir,
            config=config,
            dry_run=request.dry_run,
            log_path=self.settings.data_dir / "artifacts" / f"{job.job_id}-mlx.log",
        )
        job.metadata["trained"] = bool(record.get("trained"))
        job.metadata["dry_run"] = request.dry_run
        job.metadata["dataset"] = {key: manifest[key] for key in ("dataset_version", "train_count", "real_train_count", "synthetic_train_count", "validation_count", "train_sha256", "mixture_share")}
        job.counts = {"train_rows": int(manifest["train_count"]), "trained": 1 if record.get("trained") else 0}
        await self.repo.save_job(job)

    async def run_collection(self, job: JobRecord, request) -> None:
        from app.research import assign_complaint_splits

        inserted = duplicates = fetched = 0
        errors: list[str] = []
        sources = ["nhtsa_complaints"]
        if request.include_recalls:
            sources.append("nhtsa_recalls")
        now = datetime.now(UTC)
        for vehicle in request.vehicles:
            params = {"make": vehicle.make, "model": vehicle.model, "modelYear": vehicle.model_year}
            for source in sources:
                url = NHTSA_COMPLAINTS_URL if source == "nhtsa_complaints" else NHTSA_RECALLS_URL
                try:
                    payload = await _get_json_with_retry(url, params, self.settings.nhtsa_timeout_seconds)
                except Exception as exc:
                    errors.append(f"{source} {vehicle.make} {vehicle.model} {vehicle.model_year}: {exc}")
                    continue
                if source == "nhtsa_complaints":
                    docs = parse_complaint_payload(payload, retrieved_at=now, max_records=request.max_records_each)
                else:
                    docs = parse_recall_payload(payload, retrieved_at=now, max_records=request.max_records_each)
                fetched += len(docs)
                for document in docs:
                    outcome = await self.repo.upsert_document(document)
                    if outcome == "duplicate":
                        duplicates += 1
                        continue
                    await self.repo.replace_chunks(document.document_id, chunks_for_document(document))
                    inserted += 1
        if request.assign_splits:
            manifest = await assign_complaint_splits(self.repo, self.settings.data_dir / "splits", seed=self.settings.split_seed)
            job.metadata["split_manifest"] = manifest.get("path")
            job.metadata["split_counts"] = manifest.get("counts")
        self.state["index"] = await rebuild_index(self.repo)
        job.counts = {"fetched": fetched, "inserted": inserted, "duplicates": duplicates}
        job.errors.extend(errors)
        await self.repo.save_job(job)
        if inserted == 0 and errors:
            raise RuntimeError("; ".join(errors))


async def _get_json_with_retry(url: str, params: dict, timeout: float) -> dict:
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(3):
            try:
                return await fetch_json(client, url, params)
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"NHTSA request failed after retries: {last_error}")


async def rule_filter_all(repo) -> dict[str, int]:
    examples = await repo.list_synthetic(limit=5000)
    counts = apply_rule_filter(examples)
    for example in examples:
        await repo.save_synthetic(example)
    return counts
