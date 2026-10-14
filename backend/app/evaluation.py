"""Run evaluations and store only measured metrics."""

from __future__ import annotations

import json
import platform
import resource
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.extraction import extract_rules, target_from_result
from app.metrics import (
    abstention_counts,
    bootstrap_ci,
    dtc_counts,
    exact_match_rate,
    hallucination_rate,
    mean_defined,
    mrr,
    precision_at_k,
    recall_at_k,
    scalar_counts,
    schema_valid_rate,
)
from app.ml_baseline import plan_mixture, train_component_classifier
from app.mlx_train import read_manifest
from app.providers import build_provider, run_qa
from app.schemas import ExperimentRun, ExtractionTarget, QAFilters

SCALAR_FIELDS = ["symptom", "component", "suspected_component", "repair_action", "complaint", "cause", "correction"]


def hardware_info() -> dict:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = usage.ru_maxrss
    # macOS reports bytes; Linux reports kilobytes.
    rss_bytes = rss if platform.system() == "Darwin" else rss * 1024
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "max_rss_bytes": rss_bytes,
        "processor_note": "Apple Silicon if machine is arm64. No CUDA is assumed or measured.",
    }


def _now() -> datetime:
    return datetime.now(UTC)


async def evaluate_extraction_rules(repo) -> ExperimentRun:
    started = time.perf_counter()
    gold = await repo.list_gold()
    test = [item for item in gold if item.split == "test"]
    started_at = _now()
    if len(test) < 1:
        return _finish(
            task="extraction_rules",
            status="unavailable",
            metrics={"reason": "no test-split gold examples"},
            started_at=started_at,
            elapsed=time.perf_counter() - started,
        )
    pairs = []
    flags = []
    errors = []
    per_example_f1 = []
    for example in test:
        prediction = extract_rules(example.input_text, provider_name="rules", demo=True, model="rules-v1")
        pred_target = target_from_result(prediction)
        pairs.append((example.target, pred_target))
        flags.append(prediction.schema_valid)
        field_scores = []
        for field in ("symptom", "component"):
            stats = scalar_counts([getattr(example.target, field)], [getattr(pred_target, field)])
            if stats["f1"] is not None:
                field_scores.append(float(stats["f1"]))
        if field_scores:
            per_example_f1.append(sum(field_scores) / len(field_scores))
        if example.target.model_dump() != pred_target.model_dump():
            errors.append(
                {
                    "example_id": example.example_id,
                    "category": _error_category(example.target, pred_target),
                    "gold": example.target.model_dump(mode="json"),
                    "pred": pred_target.model_dump(mode="json"),
                }
            )
    metrics = {
        "fields": {
            field: scalar_counts(
                [getattr(gold_t, field) for gold_t, _ in pairs],
                [getattr(pred_t, field) for _, pred_t in pairs],
            )
            for field in SCALAR_FIELDS
        },
        "dtc": dtc_counts(
            [g.dtc_codes for g, _ in pairs],
            [p.dtc_codes for _, p in pairs],
        ),
        "exact_match": exact_match_rate(pairs),
        "schema_valid": schema_valid_rate(flags),
        "hallucination": hallucination_rate([g for g, _ in pairs], [p for _, p in pairs]),
        "bootstrap_mean_field_f1": bootstrap_ci(per_example_f1) if per_example_f1 else {"mean": None, "reason": "no per-example F1"},
        "support_test": len(test),
        "error_analysis": errors[:50],
        "error_count": len(errors),
        "definitions": {
            "field_f1": "Positive class is a non-null gold value. Null/null is a true negative and is excluded.",
            "hallucination_rate": "Predicted non-null scalars or DTCs that do not match gold, divided by predicted non-null items.",
        },
        "dataset_version": "demo-gold-1.0.0",
        "caveat": "Scores are on the hand-authored DEMO gold split only.",
    }
    return _finish(
        task="extraction_rules",
        status="completed",
        metrics=metrics,
        started_at=started_at,
        elapsed=time.perf_counter() - started,
        dataset_ids=[item.example_id for item in test],
    )


async def evaluate_classifier(repo) -> ExperimentRun:
    started = time.perf_counter()
    gold = [item for item in await repo.list_gold() if item.component_category]
    train = [item for item in gold if item.split == "train"]
    test = [item for item in gold if item.split == "test"]
    result = train_component_classifier(
        [item.input_text for item in train],
        [item.component_category or "" for item in train],
        [item.input_text for item in test],
        [item.component_category or "" for item in test],
    )
    # Drop bulky prediction lists from the stored view after scoring errors.
    predictions = result.pop("predictions", [])
    labels = result.pop("labels", [])
    errors = []
    test_ids = [item.example_id for item in test]
    for example_id, gold_label, pred in zip(test_ids, labels, predictions, strict=False):
        if gold_label != pred:
            errors.append({"example_id": example_id, "category": "wrong_category", "gold": gold_label, "pred": pred})
    result["error_analysis"] = errors[:50]
    status = "completed" if result.get("status") == "measured" else "unavailable"
    return _finish(
        task="component_classifier",
        status=status,
        metrics=result,
        started_at=_now(),
        elapsed=time.perf_counter() - started,
        dataset_ids=test_ids,
    )


async def evaluate_retrieval(repo, index, qa_labels: list[dict]) -> ExperimentRun:
    started = time.perf_counter()
    if not qa_labels:
        return _finish(
            task="retrieval_comparison",
            status="unavailable",
            metrics={"reason": "no QA relevance labels"},
            started_at=_now(),
            elapsed=time.perf_counter() - started,
        )
    modes = ["lexical", "vector", "hybrid"]
    by_mode: dict[str, dict] = {}
    for mode in modes:
        recalls, mrrs, precisions = [], [], []
        for label in qa_labels:
            filters = QAFilters.model_validate(label.get("filters") or {})
            hits, _meta = index.search(label["question"], filters=filters, top_k=5, mode=mode)
            ranked_docs = []
            for hit in hits:
                if hit.document_id not in ranked_docs:
                    ranked_docs.append(hit.document_id)
            relevant = set(label.get("relevant_document_ids") or [])
            recalls.append(recall_at_k(relevant, ranked_docs, 5))
            precisions.append(precision_at_k(relevant, ranked_docs, 5))
            mrrs.append(mrr(relevant, ranked_docs))
        by_mode[mode] = {
            "recall_at_5": mean_defined(recalls),
            "precision_at_5": mean_defined(precisions),
            "mrr": mean_defined(mrrs),
            "support": len(qa_labels),
        }
    return _finish(
        task="retrieval_comparison",
        status="completed",
        metrics={
            "modes": by_mode,
            "fusion": "reciprocal_rank_fusion k=60 when hybrid",
            "vector": index.status().get("vector"),
            "caveat": "Relevance labels are hand-assigned on DEMO questions.",
        },
        started_at=_now(),
        elapsed=time.perf_counter() - started,
        dataset_ids=[item["question_id"] for item in qa_labels],
    )


async def evaluate_provider_extraction(repo, settings, provider=None) -> ExperimentRun:
    """Score the selected provider. An unavailable model is an unavailable run."""
    started = time.perf_counter()
    started_at = _now()
    provider = provider or build_provider(settings.provider, settings)
    health = await provider.health()
    name = getattr(provider, "name", settings.provider)
    revision = getattr(provider, "model", None)
    if not health.available:
        return _finish(
            task="extraction_provider",
            status="unavailable",
            metrics={"reason": health.detail, "provider": name, "measured": False},
            started_at=started_at,
            elapsed=time.perf_counter() - started,
            model_provider=name,
            model_revision=revision,
            caveat=health.detail,
        )
    gold = await repo.list_gold()
    test = [item for item in gold if item.split == "test"]
    if not test:
        return _finish(
            task="extraction_provider",
            status="unavailable",
            metrics={"reason": "no test-split gold examples", "provider": name},
            started_at=started_at,
            elapsed=time.perf_counter() - started,
            model_provider=name,
            model_revision=revision,
        )
    pairs = []
    flags = []
    errors = []
    per_example_f1 = []
    for example in test:
        try:
            prediction = await provider.extract(example.input_text, None)
        except Exception as exc:
            flags.append(False)
            errors.append({"example_id": example.example_id, "category": "provider_error", "detail": exc.__class__.__name__})
            continue
        pred_target = target_from_result(prediction)
        pairs.append((example.target, pred_target))
        flags.append(prediction.schema_valid)
        field_scores = []
        for field in ("symptom", "component"):
            stats = scalar_counts([getattr(example.target, field)], [getattr(pred_target, field)])
            if stats["f1"] is not None:
                field_scores.append(float(stats["f1"]))
        if field_scores:
            per_example_f1.append(sum(field_scores) / len(field_scores))
        if example.target.model_dump() != pred_target.model_dump():
            errors.append(
                {
                    "example_id": example.example_id,
                    "category": _error_category(example.target, pred_target),
                    "gold": example.target.model_dump(mode="json"),
                    "pred": pred_target.model_dump(mode="json"),
                    "prediction_source": prediction.provider.provider,
                }
            )
    caveat = (
        "Scores are for the selected provider on the held-out gold split. "
        "Demo provider results are rules, not a fine-tuned LLM."
        if name == "demo"
        else "Scores are for the selected model provider on the held-out gold split."
    )
    metrics = {
        "provider": name,
        "is_llm": bool(health.is_llm),
        "demo": bool(health.demo),
        "fields": {
            field: scalar_counts(
                [getattr(gold_t, field) for gold_t, _ in pairs],
                [getattr(pred_t, field) for _, pred_t in pairs],
            )
            for field in SCALAR_FIELDS
        } if pairs else {},
        "dtc": dtc_counts([g.dtc_codes for g, _ in pairs], [p.dtc_codes for _, p in pairs]) if pairs else None,
        "exact_match": exact_match_rate(pairs) if pairs else None,
        "schema_valid": schema_valid_rate(flags) if flags else None,
        "hallucination": hallucination_rate([g for g, _ in pairs], [p for _, p in pairs]) if pairs else None,
        "bootstrap_mean_field_f1": bootstrap_ci(per_example_f1) if per_example_f1 else {"mean": None, "reason": "no per-example F1"},
        "support_test": len(test),
        "scored": len(pairs),
        "error_analysis": errors[:50],
        "error_count": len(errors),
        "caveat": caveat,
    }
    return _finish(
        task="extraction_provider",
        status="completed" if pairs else "unavailable",
        metrics=metrics,
        started_at=started_at,
        elapsed=time.perf_counter() - started,
        dataset_ids=[item.example_id for item in test],
        model_provider=name,
        model_revision=revision,
        caveat=caveat,
    )


async def evaluate_qa(repo, index, qa_labels: list[dict], settings, provider=None) -> ExperimentRun:
    del repo
    started = time.perf_counter()
    provider = provider or build_provider(settings.provider, settings)
    health = await provider.health()
    name = getattr(provider, "name", "unknown")
    if not health.available:
        return _finish(
            task="qa_rag",
            status="unavailable",
            metrics={"reason": health.detail, "provider": name, "measured": False},
            started_at=_now(),
            elapsed=time.perf_counter() - started,
            model_provider=name,
            model_revision=getattr(provider, "model", None),
            caveat=health.detail or "provider unavailable",
        )
    answerable = []
    abstained = []
    citation_hits = []
    fact_hits = []
    latencies = []
    errors = []
    for label in qa_labels:
        filters = QAFilters.model_validate(label.get("filters") or {})
        hits, meta = index.search(label["question"], filters=filters, top_k=5, mode="hybrid")
        response = await run_qa(
            provider,
            label["question"],
            hits,
            filters,
            min_score=settings.bm25_min_score,
            retrieval_meta=meta,
        )
        answerable.append(bool(label.get("answerable")))
        abstained.append(response.abstained)
        latencies.append(response.latency_ms)
        relevant = set(label.get("relevant_document_ids") or [])
        retrieved = {hit.document_id for hit in hits}
        cited_docs = [citation.document_id for citation in response.citations]
        if label.get("answerable"):
            if response.citations:
                citation_hits.append(float(set(cited_docs).issubset(retrieved | relevant) and set(cited_docs).issubset(relevant or retrieved)))
            else:
                citation_hits.append(0.0)
            blob = response.answer.lower()
            required = [fact.lower() for fact in label.get("required_facts") or []]
            forbidden = [fact.lower() for fact in label.get("forbidden_claims") or []]
            ok = all(fact in blob for fact in required) and not any(fact in blob for fact in forbidden)
            fact_hits.append(1.0 if ok else 0.0)
            if not ok or response.abstained:
                errors.append({"question_id": label["question_id"], "category": "qa_miss_or_abstain", "abstained": response.abstained})
        elif not response.abstained:
            errors.append({"question_id": label["question_id"], "category": "failed_to_abstain"})
    metrics = {
        "abstention": abstention_counts(answerable, abstained),
        "answer_fact_rate": mean_defined(fact_hits),
        "citation_support_rate": mean_defined(citation_hits),
        "latency_ms_mean": mean_defined(latencies),
        "support": len(qa_labels),
        "error_analysis": errors[:50],
        "provider": name,
        "is_llm": bool(health.is_llm),
        "demo": bool(health.demo),
        "claim_method": "required and forbidden phrase match plus citation id checks. This is not claim-level human grading.",
        "caveat": "Fact rate checks required phrases on the stored labels. It is not a human grading study. The provider recorded above is the one that answered.",
    }
    return _finish(
        task="qa_rag",
        status="completed" if qa_labels else "unavailable",
        metrics=metrics,
        started_at=_now(),
        elapsed=time.perf_counter() - started,
        dataset_ids=[item["question_id"] for item in qa_labels],
        model_provider=name,
        model_revision=getattr(provider, "model", None),
    )


async def evaluate_synthetic_share(repo) -> ExperimentRun:
    started = time.perf_counter()
    gold = [item for item in await repo.list_gold() if item.component_category]
    real = [item for item in gold if item.split == "train"]
    test = [item for item in gold if item.split == "test"]
    synthetic = [
        item
        for item in await repo.list_synthetic()
        if item.review_status == "approved" and item.split == "train"
    ]
    arms = []
    target_n = len(real)
    parent_id = f"exp_{uuid.uuid4().hex[:12]}"
    for share in (0.0, 0.25, 0.5, 0.75, 1.0):
        plan, reason = plan_mixture(len(real), len(synthetic), share, target_n)
        if plan is None or not test:
            arms.append({"synthetic_share": share, "status": "skipped", "reason": reason or "no test labels", "macro_f1": None})
            continue
        n_real, n_syn = plan
        texts = [item.input_text for item in real[:n_real]]
        labels = [item.component_category or "" for item in real[:n_real]]
        for example in synthetic[:n_syn]:
            category = _category_from_target(example.expected_json)
            if not category:
                continue
            texts.append(example.input_text)
            labels.append(category)
        if len(texts) < 4:
            arms.append({"synthetic_share": share, "status": "skipped", "reason": "mixture smaller than 4 after label mapping", "macro_f1": None})
            continue
        scored = train_component_classifier(
            texts,
            labels,
            [item.input_text for item in test],
            [item.component_category or "" for item in test],
        )
        arms.append(
            {
                "synthetic_share": share,
                "status": scored["status"],
                "macro_f1": scored.get("macro_f1"),
                "support_train": len(texts),
                "reason": scored.get("reason"),
            }
        )
    measured = [arm for arm in arms if arm.get("macro_f1") is not None]
    return _finish(
        task="synthetic_share",
        status="completed" if measured else "unavailable",
        metrics={
            "arms": arms,
            "target_n": target_n,
            "real_train": len(real),
            "approved_synthetic": len(synthetic),
            "system": "tfidf_logistic_regression",
            "measures_llm": False,
            "caveat": "This arm scores a TF-IDF logistic regression component classifier. It is not a fine-tuned LLM extraction curve. Skipped arms are not interpolated.",
        },
        started_at=_now(),
        elapsed=time.perf_counter() - started,
        run_id=parent_id,
    )


async def evaluate_filtered_vs_unfiltered(repo) -> ExperimentRun:
    started = time.perf_counter()
    gold = [item for item in await repo.list_gold() if item.component_category]
    test = [item for item in gold if item.split == "test"]
    synthetic = [item for item in await repo.list_synthetic() if item.split == "train"]
    filtered = [item for item in synthetic if item.review_status == "approved"]
    unfiltered = [item for item in synthetic if item.review_status != "rejected"]
    real = [item for item in gold if item.split == "train"]

    def rows(extra):
        texts = [item.input_text for item in real]
        labels = [item.component_category or "" for item in real]
        for example in extra:
            category = _category_from_target(example.expected_json)
            if category:
                texts.append(example.input_text)
                labels.append(category)
        return texts, labels

    results = {}
    for name, subset in (("filtered", filtered), ("unfiltered", unfiltered)):
        if not subset:
            results[name] = {"status": "skipped", "reason": f"no {name} synthetic examples", "macro_f1": None}
            continue
        texts, labels = rows(subset)
        scored = train_component_classifier(
            texts,
            labels,
            [item.input_text for item in test],
            [item.component_category or "" for item in test],
        )
        results[name] = {"status": scored["status"], "macro_f1": scored.get("macro_f1"), "support_train": len(texts), "reason": scored.get("reason")}
    measured = any(item.get("macro_f1") is not None for item in results.values())
    return _finish(
        task="filtered_vs_unfiltered",
        status="completed" if measured else "unavailable",
        metrics={"comparison": results, "caveat": "Unfiltered excludes rule-rejected rows and still requires labels."},
        started_at=_now(),
        elapsed=time.perf_counter() - started,
    )


async def evaluate_synthetic_share_llm(repo, settings) -> ExperimentRun:
    """The LLM mixture curve is unavailable until separate trained adapters exist.

    This function does not copy classifier F1 into an LLM chart.
    """
    del repo
    started = time.perf_counter()
    manifest = read_manifest(settings.resolved_adapter_dir)
    trained = bool(manifest and manifest.get("trained"))
    reason = (
        "One completed adapter does not measure synthetic-share proportions. "
        "Train a fresh adapter per share, then run extraction_provider on the held-out gold set. "
        "Classifier F1 is not reused here."
        if trained
        else "No completed MLX adapter is stored, so the fine-tuned LLM synthetic-share curve was not measured."
    )
    return _finish(
        task="synthetic_share_llm",
        status="unavailable",
        metrics={
            "reason": reason,
            "measured": False,
            "adapter_trained": trained,
            "arms": [],
            "system": "fine_tuned_llm",
            "measures_llm": False,
        },
        started_at=_now(),
        elapsed=time.perf_counter() - started,
        model_provider="mlx",
        model_revision=(manifest or {}).get("base_model"),
        caveat=reason,
    )


def write_error_export(path: Path, run: ExperimentRun) -> str | None:
    errors = (run.metrics or {}).get("error_analysis")
    if not errors:
        return None
    path.mkdir(parents=True, exist_ok=True)
    target = path / f"{run.run_id}_errors.json"
    target.write_text(json.dumps({"run_id": run.run_id, "errors": errors}, indent=2), encoding="utf-8")
    return str(target)


def _category_from_target(target: ExtractionTarget) -> str | None:
    component = (target.component or target.suspected_component or "").lower()
    mapping = {
        "catalytic converter": "emissions",
        "front brake pads": "brakes",
        "brake pads": "brakes",
        "brake rotors": "brakes",
        "radio": "electrical",
        "shift solenoid": "drivetrain",
        "wheel speed sensor": "brakes",
    }
    for key, category in mapping.items():
        if key in component:
            return category
    if target.symptom and "cold" in target.symptom:
        return "hvac"
    if target.dtc_codes and any(code.startswith("P030") for code in target.dtc_codes):
        return "engine"
    if target.dtc_codes and any(code in {"P0420", "P0430", "P0171"} for code in target.dtc_codes):
        return "emissions"
    return None


def _error_category(gold: ExtractionTarget, pred: ExtractionTarget) -> str:
    if gold.dtc_codes != pred.dtc_codes:
        return "dtc_mismatch"
    if gold.component != pred.component:
        if pred.component and not gold.component:
            return "unsupported_component"
        return "component_mismatch"
    if gold.symptom != pred.symptom:
        return "symptom_mismatch"
    return "other_field_mismatch"


def _finish(
    *,
    task: str,
    status: str,
    metrics: dict,
    started_at: datetime,
    elapsed: float,
    dataset_ids: list[str] | None = None,
    run_id: str | None = None,
    model_provider: str | None = None,
    model_revision: str | None = None,
    caveat: str | None = None,
) -> ExperimentRun:
    if model_provider is None:
        model_provider = "deterministic_demo" if task in {"extraction_rules", "qa_rag"} or task.startswith("extraction") else "tfidf-logreg-v1"
        if task in {"component_classifier", "synthetic_share", "filtered_vs_unfiltered"}:
            model_provider = "tfidf-logreg-v1"
        elif task == "retrieval_comparison":
            model_provider = "bm25-tfidf"
        elif task == "extraction_rules":
            model_provider = "rules"
    if model_revision is None:
        model_revision = "rules-v1" if task == "extraction_rules" else None
    note = caveat or metrics.get("caveat")
    return ExperimentRun(
        run_id=run_id or f"run_{uuid.uuid4().hex[:12]}",
        task=task,
        model_provider=model_provider,
        model_revision=model_revision,
        dataset_ids=dataset_ids or [],
        dataset_version="demo-1.0.0",
        metrics=metrics,
        runtime_seconds=round(elapsed, 4),
        hardware=hardware_info(),
        commit_hash=None,
        status=status,
        started_at=started_at,
        finished_at=_now(),
        caveats=[note] if note else [],
        training_settings={"seed": 42, "test_split_excluded_from_training": True},
    )
