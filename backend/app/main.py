"""AutoRO-LM FastAPI application."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app import SCHEMA_VERSION, __version__
from app.bootstrap import load_demo_fixtures, load_qa_labels, rebuild_index
from app.config import REPO_ROOT, get_settings
from app.errors import AppError, NotFoundError, RateLimited
from app.ingestion import profile_documents
from app.jobs import JobRunner, new_job, rule_filter_all
from app.logging_config import configure_logging
from app.providers import build_provider, run_qa
from app.repository import SQLiteRepository
from app.schemas import (
    SAFETY_NOTICE,
    AskRequest,
    CollectionRequest,
    DatabaseStatus,
    EligibilityRequest,
    EvaluationRequest,
    ExtractRequest,
    GoldExample,
    GoldWriteRequest,
    HealthResponse,
    IngestionJobRequest,
    QAFilters,
    ResetRequest,
    ReviewRequest,
    SettingsUpdate,
    SettingsView,
    SplitAssignRequest,
    StatusResponse,
    SyntheticJobRequest,
    TrainingJobRequest,
)
from app.synthetic import dedupe
from app.textutil import normalize_whitespace

logger = logging.getLogger("autoro.api")
_HITS: dict[str, list[float]] = defaultdict(list)


def _database_status(settings, active: str, connected: bool, fallback: bool, detail: str) -> DatabaseStatus:
    configured = "mongodb" if settings.database_url.startswith("mongodb") else "sqlite"
    return DatabaseStatus(
        configured_adapter=configured,
        active_adapter=active,
        connected=connected,
        fallback=fallback,
        detail=detail,
        path=None if active == "mongodb" else str(settings.sqlite_path),
    )


async def _open_repository(settings, state: dict):
    if settings.database_url.startswith("mongodb"):
        from app.mongo_repository import MongoRepository

        mongo = MongoRepository(settings.database_url, settings.mongo_db)
        try:
            await mongo.connect()
        except Exception as exc:
            detail = f"MongoDB was configured but is not connected ({exc.__class__.__name__}: {exc}). Using SQLite."
            logger.warning(detail)
            repo = SQLiteRepository(settings.sqlite_path)
            await repo.connect()
            state["database"] = _database_status(settings, "sqlite", True, True, detail)
            return repo
        state["database"] = _database_status(settings, "mongodb", True, False, "Connected to the configured MongoDB database.")
        return mongo
    repo = SQLiteRepository(settings.sqlite_path)
    await repo.connect()
    state["database"] = _database_status(
        settings,
        "sqlite",
        True,
        False,
        "SQLite file adapter. MongoDB is not configured.",
    )
    return repo


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(settings.log_level)
    state: dict = {}
    repo = await _open_repository(settings, state)
    for key in ("provider", "teacher_provider", "retrieval_mode"):
        saved = await repo.get_setting(key)
        if saved:
            setattr(settings, key, saved)
    await repo.fail_interrupted_jobs()
    await load_demo_fixtures(repo, settings.demo_dir, force=False)
    index = await rebuild_index(repo)
    state["settings"] = settings
    state["repo"] = repo
    state["index"] = index
    state["qa_labels"] = load_qa_labels(settings.demo_dir)
    state["jobs"] = JobRunner(settings, repo, state)
    app.state.autoro = state
    try:
        yield
    finally:
        await repo.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AutoRO-LM",
        version=__version__,
        summary="Automotive repair-text extraction and source-grounded QA research API.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled", extra={"request_id": request_id, "path": request.url.path, "method": request.method})
            raise
        latency = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "latency_ms": latency,
            },
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_error(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=_error("validation_error", "Request validation failed", exc.errors()))

    def state():
        return app.state.autoro

    def limit(request: Request, bucket: str) -> None:
        settings = state()["settings"]
        forwarded = request.client.host if request.client else "local"
        key = f"{bucket}:{forwarded}"
        now = time.time()
        hits = [stamp for stamp in _HITS[key] if now - stamp < 60]
        if len(hits) >= settings.rate_limit_per_minute:
            raise RateLimited("Rate limit exceeded. Wait a minute and retry.")
        hits.append(now)
        _HITS[key] = hits

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health():
        ctx = state()
        settings = ctx["settings"]
        providers = []
        for role, name in (("extraction_and_qa", settings.provider), ("teacher", _teacher_name(settings))):
            if role == "teacher" and settings.teacher_provider == "none":
                from app.schemas import ProviderHealth

                providers.append(
                    ProviderHealth(
                        name="none",
                        role="teacher",
                        available=False,
                        is_llm=False,
                        demo=False,
                        detail="Synthetic teacher is disabled.",
                    )
                )
                continue
            provider = build_provider(name if role == "extraction_and_qa" else _teacher_runtime(settings), settings)
            item = await provider.health()
            item.role = role
            if role == "teacher" and settings.teacher_provider == "deterministic_demo":
                item.name = "deterministic_demo"
                item.detail = "Deterministic paraphraser over facts supported by the seed. Not a language model."
            providers.append(item)
        degraded = any(not item.available for item in providers if item.role == "extraction_and_qa")
        return HealthResponse(
            status="degraded" if degraded or not ctx["database"].connected else "ok",
            version=__version__,
            schema_version=SCHEMA_VERSION,
            demo_provider=settings.provider == "demo",
            database=ctx["database"],
            providers=providers,
            retrieval=ctx["index"].status(),
        )

    @app.get("/api/v1/status", response_model=StatusResponse)
    async def status():
        ctx = state()
        settings = ctx["settings"]
        counts = await ctx["repo"].counts()
        providers = []
        extraction = build_provider(settings.provider, settings)
        providers.append(await extraction.health())
        teacher = build_provider(_teacher_runtime(settings), settings) if settings.teacher_provider != "none" else None
        if teacher:
            item = await teacher.health()
            item.role = "teacher"
            providers.append(item)
        return StatusResponse(
            demo_data=counts.get("non_demo_documents", 0) == 0,
            demo_provider=settings.provider == "demo",
            database=ctx["database"],
            counts=counts,
            index=ctx["index"].status(),
            providers=providers,
            recent_jobs=await ctx["repo"].list_jobs(8),
            evaluation_count=counts.get("experiments", 0),
            safety_notice=SAFETY_NOTICE,
        )

    @app.post("/api/v1/extract")
    async def extract(body: ExtractRequest, request: Request):
        limit(request, "extract")
        ctx = state()
        settings = ctx["settings"]
        if len(body.text) > settings.max_extract_chars:
            raise AppError(f"Text exceeds {settings.max_extract_chars} characters", details=None)
        name = body.provider or settings.provider
        provider = build_provider(name, settings)
        health = await provider.health()
        if not health.available:
            from app.errors import ProviderUnavailable

            raise ProviderUnavailable(health.detail or f"{name} is unavailable")
        result = await provider.extract(normalize_whitespace(body.text), body.vehicle)
        await ctx["repo"].add_audit(
            "extract",
            {"provider": name, "chars": len(body.text), "demo": result.demo, "schema_valid": result.schema_valid},
        )
        return result

    @app.post("/api/v1/ask")
    async def ask(body: AskRequest, request: Request):
        limit(request, "ask")
        ctx = state()
        settings = ctx["settings"]
        name = body.provider or settings.provider
        provider = build_provider(name, settings)
        health = await provider.health()
        if not health.available:
            from app.errors import ProviderUnavailable

            raise ProviderUnavailable(health.detail or f"{name} is unavailable")
        mode = body.retrieval_mode or settings.retrieval_mode
        chunks, meta = ctx["index"].search(body.question, filters=body.filters, top_k=body.top_k, mode=mode)
        return await run_qa(
            provider,
            body.question,
            chunks,
            body.filters or QAFilters(),
            min_score=settings.bm25_min_score,
            retrieval_meta=meta,
        )

    @app.get("/api/v1/sources")
    async def list_sources(source_type: str | None = None, limit: int = 25, offset: int = 0, demo: bool | None = None):
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        docs = await state()["repo"].list_documents(source_type=source_type, limit=limit, offset=offset, demo=demo)
        return {"items": docs, "limit": limit, "offset": offset, "count": len(docs)}

    @app.get("/api/v1/sources/profile")
    async def source_profile():
        docs = await state()["repo"].all_documents()
        return profile_documents(docs)

    @app.get("/api/v1/sources/{document_id}")
    async def get_source(document_id: str):
        repo = state()["repo"]
        document = await repo.get_document(document_id)
        if document is None:
            raise NotFoundError(f"No document {document_id}")
        chunks = await repo.chunks_for(document_id)
        return {"document": document, "chunks": chunks}

    @app.post("/api/v1/ingestion/jobs")
    async def start_ingestion(body: IngestionJobRequest, request: Request):
        limit(request, "ingestion")
        ctx = state()
        job = new_job("ingestion", body.source, body.model_dump(mode="json"))
        runner: JobRunner = ctx["jobs"]

        async def worker(current):
            await runner.run_ingestion(current, body)

        return await runner.submit(job, worker)

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: str):
        job = await state()["repo"].get_job(job_id)
        if job is None:
            raise NotFoundError(f"No job {job_id}")
        return job

    @app.get("/api/v1/jobs")
    async def list_jobs(limit: int = 20):
        return {"items": await state()["repo"].list_jobs(max(1, min(limit, 100)))}

    @app.post("/api/v1/synthetic/jobs")
    async def start_synthetic(body: SyntheticJobRequest, request: Request):
        limit(request, "synthetic")
        ctx = state()
        settings = ctx["settings"]
        if body.count > settings.max_synthetic_count:
            raise AppError(f"count exceeds the configured maximum of {settings.max_synthetic_count}")
        if body.teacher == "deterministic_demo" and settings.teacher_provider == "none":
            from app.errors import ProviderUnavailable

            raise ProviderUnavailable("Synthetic generation is disabled because no teacher provider is configured.")
        if body.teacher == "ollama":
            provider = build_provider("ollama", settings)
            health = await provider.health()
            if not health.available:
                from app.errors import ProviderUnavailable

                raise ProviderUnavailable(health.detail or "Ollama teacher is unavailable")
        job = new_job("synthetic", body.teacher, {"count": body.count, "variations": body.variations, "is_llm": body.teacher == "ollama"})
        runner: JobRunner = ctx["jobs"]

        async def worker(current):
            await runner.run_synthetic(current, body)

        return await runner.submit(job, worker)

    @app.get("/api/v1/synthetic/jobs/{job_id}")
    async def synthetic_job(job_id: str):
        return await get_job(job_id)

    @app.get("/api/v1/synthetic/examples")
    async def list_synthetic(status: str | None = None, limit: int = 50, offset: int = 0):
        items = await state()["repo"].list_synthetic(status=status, limit=max(1, min(limit, 200)), offset=max(0, offset))
        return {"items": items, "limit": limit, "offset": offset, "count": len(items)}

    @app.post("/api/v1/synthetic/examples/{example_id}/review")
    async def review_example(example_id: str, body: ReviewRequest):
        repo = state()["repo"]
        example = await repo.get_synthetic(example_id)
        if example is None:
            raise NotFoundError(f"No synthetic example {example_id}")
        example.review_status = body.status
        example.review_reason = body.reason
        await repo.save_synthetic(example)
        await repo.add_audit("synthetic_review", {"example_id": example_id, "status": body.status})
        return example

    @app.post("/api/v1/synthetic/rule-filter")
    async def rule_filter():
        counts = await rule_filter_all(state()["repo"])
        return {"label": "rule_filter_not_human_review", **counts}

    @app.post("/api/v1/synthetic/dedupe")
    async def dedupe_examples():
        repo = state()["repo"]
        examples = await repo.list_synthetic(limit=5000)
        rejected_ids = dedupe(examples)
        for example in examples:
            await repo.save_synthetic(example)
        return {"rejected": len(rejected_ids), "example_ids": rejected_ids}

    @app.get("/api/v1/synthetic/examples/export")
    async def export_synthetic():
        examples = await state()["repo"].list_synthetic(limit=5000)
        lines = [example.model_dump_json() for example in examples]
        body = "\n".join(lines) + ("\n" if lines else "")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "count": len(examples),
            "sha256": digest,
            "created_at": datetime.now(UTC).isoformat(),
            "label": "Includes DEMO deterministic paraphrases when generation_provider is deterministic_demo.",
        }
        payload = json.dumps(manifest) + "\n" + body
        return Response(
            content=payload,
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=synthetic_examples.jsonl"},
        )

    @app.post("/api/v1/evaluations")
    async def start_evaluation(body: EvaluationRequest, request: Request):
        limit(request, "evaluation")
        ctx = state()
        job = new_job("evaluation", body.task, {"task": body.task})
        runner: JobRunner = ctx["jobs"]

        async def worker(current):
            await runner.run_evaluation(current, body.task)

        return await runner.submit(job, worker)

    @app.get("/api/v1/evaluations")
    async def list_evaluations():
        items = await state()["repo"].list_experiments(100)
        return {"items": items}

    @app.get("/api/v1/evaluations/{run_id}")
    async def get_evaluation(run_id: str):
        run = await state()["repo"].get_experiment(run_id)
        if run is None:
            raise NotFoundError(f"No evaluation {run_id}")
        return run

    @app.get("/api/v1/evaluations/{run_id}/export")
    async def export_evaluation(run_id: str, format: str = "json"):
        run = await state()["repo"].get_experiment(run_id)
        if run is None:
            raise NotFoundError(f"No evaluation {run_id}")
        if format == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["run_id", "task", "status", "metric", "value"])
            for key, value in _flatten(run.metrics):
                writer.writerow([run.run_id, run.task, run.status, key, value])
            return Response(
                content=buffer.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={run_id}.csv"},
            )
        return Response(
            content=run.model_dump_json(indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={run_id}.json"},
        )

    @app.get("/api/v1/experiments")
    async def list_experiments():
        return {"items": await state()["repo"].list_experiments(100)}

    @app.get("/api/v1/experiments/{run_id}")
    async def get_experiment(run_id: str):
        return await get_evaluation(run_id)

    @app.get("/api/v1/settings", response_model=SettingsView)
    async def get_settings_view():
        ctx = state()
        settings = ctx["settings"]
        return SettingsView(
            environment=settings.env,
            provider=settings.provider,
            teacher_provider=settings.teacher_provider,
            retrieval_mode=settings.retrieval_mode,
            data_dir=str(settings.data_dir),
            database=ctx["database"],
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            hosted_provider_configured=bool(settings.openai_compat_base_url),
            hosted_key_present=bool(settings.openai_compat_api_key),
            max_extract_chars=settings.max_extract_chars,
            max_synthetic_count=settings.max_synthetic_count,
            jobs_inline=settings.jobs_inline,
            mlx_model=settings.mlx_model,
            mlx_adapter_dir=str(settings.resolved_adapter_dir),
            mlx_adapter_trained=_adapter_trained(settings),
            mlx_detail=_adapter_detail(settings),
            privacy_note=(
                "Extraction and QA text is not written to the database by default. "
                "Audit events store character counts, not the note. Synthetic examples, "
                "gold fixtures, and source documents are stored locally. Hosted provider "
                "calls happen only after you select that provider. Secret values are never returned."
            ),
        )

    @app.put("/api/v1/settings", response_model=SettingsView)
    async def update_settings(body: SettingsUpdate):
        ctx = state()
        settings = ctx["settings"]
        repo = ctx["repo"]
        if body.provider:
            settings.provider = body.provider
            await repo.set_setting("provider", body.provider)
        if body.teacher_provider:
            settings.teacher_provider = body.teacher_provider
            await repo.set_setting("teacher_provider", body.teacher_provider)
        if body.retrieval_mode:
            settings.retrieval_mode = body.retrieval_mode
            await repo.set_setting("retrieval_mode", body.retrieval_mode)
        return await get_settings_view()

    @app.post("/api/v1/settings/reset-demo")
    async def reset_demo(body: ResetRequest):
        if body.confirm != "RESET_DEMO_DATA":
            raise AppError("Confirmation text must be RESET_DEMO_DATA")
        ctx = state()
        result = await load_demo_fixtures(ctx["repo"], ctx["settings"].demo_dir, force=True)
        ctx["index"] = await rebuild_index(ctx["repo"])
        return result

    @app.get("/api/v1/reference/dtcs")
    async def list_dtcs(code: str | None = None):
        catalog = json.loads((REPO_ROOT / "backend" / "data" / "reference" / "dtc_generic.json").read_text(encoding="utf-8"))
        items = catalog["codes"]
        if code:
            wanted = code.strip().upper()
            items = [item for item in items if item["code"] == wanted]
        return {
            "catalog_id": catalog["catalog_id"],
            "source_note": catalog["source_note"],
            "license_notes": catalog["license_notes"],
            "count": len(items),
            "items": items,
            "failure_diagnosis": False,
        }

    @app.get("/api/v1/gold")
    async def list_gold(split: str | None = None):
        items = await state()["repo"].list_gold(split)
        return {"items": items, "count": len(items)}

    @app.post("/api/v1/gold")
    async def create_gold(body: GoldWriteRequest):
        from app.research import save_gold_example

        example = GoldExample(
            example_id=body.example_id,
            source_document_ids=body.source_document_ids,
            source_group=body.source_group,
            input_text=body.input_text,
            target=body.target,
            component_category=body.component_category,
            annotation_guideline_version=body.annotation_guideline_version,
            reviewer_notes=body.reviewer_notes,
            reviewer_id=body.reviewer_id,
            split=body.split,
            created_at=datetime.now(UTC),
            demo=body.demo,
        )
        saved = await save_gold_example(state()["repo"], example)
        return saved

    @app.post("/api/v1/sources/assign-splits")
    async def assign_splits(body: SplitAssignRequest):
        from app.research import assign_complaint_splits

        ctx = state()
        return await assign_complaint_splits(ctx["repo"], ctx["settings"].data_dir / "splits", seed=body.seed)

    @app.post("/api/v1/sources/eligibility")
    async def enable_seeds(body: EligibilityRequest):
        from app.research import enable_train_seeds

        return await enable_train_seeds(
            state()["repo"],
            confirm=body.confirm,
            document_ids=body.document_ids or None,
        )

    @app.post("/api/v1/ingestion/collection")
    async def start_collection(body: CollectionRequest, request: Request):
        limit(request, "ingestion")
        ctx = state()
        job = new_job("ingestion", "nhtsa_collection", {"vehicles": len(body.vehicles)})
        runner: JobRunner = ctx["jobs"]

        async def worker(current):
            await runner.run_collection(current, body)

        return await runner.submit(job, worker)

    @app.post("/api/v1/training/datasets")
    async def build_dataset(body: TrainingJobRequest):
        from app.training_data import build_training_dataset

        ctx = state()
        share_label = str(int(round(body.mixture_share * 100)))
        dest = ctx["settings"].data_dir / "training" / f"share-{share_label}"
        return await build_training_dataset(ctx["repo"], dest, mixture_share=body.mixture_share)

    @app.post("/api/v1/training/jobs")
    async def start_training(body: TrainingJobRequest, request: Request):
        limit(request, "training")
        ctx = state()
        job = new_job("training", "mlx_lora", {"dry_run": body.dry_run, "mixture_share": body.mixture_share})
        runner: JobRunner = ctx["jobs"]

        async def worker(current):
            await runner.run_training(current, body)

        return await runner.submit(job, worker)

    @app.get("/api/v1/training/adapter")
    async def adapter_status():
        settings = state()["settings"]
        return {
            "model": settings.mlx_model,
            "adapter_dir": str(settings.resolved_adapter_dir),
            "trained": _adapter_trained(settings),
            "detail": _adapter_detail(settings),
        }

    return app


def _adapter_trained(settings) -> bool:
    from app.mlx_train import read_manifest

    manifest = read_manifest(settings.resolved_adapter_dir)
    return bool(manifest and manifest.get("trained"))


def _adapter_detail(settings) -> str:
    from app.mlx_train import mlx_available, read_manifest

    ok, detail = mlx_available()
    manifest = read_manifest(settings.resolved_adapter_dir)
    if manifest and manifest.get("dry_run") and not manifest.get("trained"):
        return "The last MLX record is a dry run. No adapter was trained."
    if not ok:
        return detail
    if not manifest:
        return "mlx-lm imports, and no adapter manifest is stored yet."
    if manifest.get("trained"):
        return f"Adapter trained from {manifest.get('base_model')}."
    return manifest.get("detail") or "Adapter manifest exists and trained is false."


def _teacher_name(settings) -> str:
    return settings.teacher_provider


def _teacher_runtime(settings) -> str:
    if settings.teacher_provider == "deterministic_demo":
        return "demo"
    if settings.teacher_provider == "ollama":
        return "ollama"
    return "demo"


def _error(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _flatten(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        yield prefix or "value", json.dumps(value)
    else:
        yield prefix or "value", value


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
