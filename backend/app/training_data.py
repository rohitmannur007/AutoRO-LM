"""Build MLX chat JSONL from train-split labels only.

Test and validation gold rows are never written into train.jsonl.
Synthetic rows must be approved, train-split, and free of test-document seeds.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.ml_baseline import plan_mixture
from app.schemas import ExtractionTarget

PROMPT = (
    "Extract automotive repair fields as JSON. Use null for any field the text does not support. "
    "Do not invent a DTC, a failed part, or a completed repair. A DTC alone is not proof a component failed. "
    "Keys: symptom, dtc_codes, component, suspected_component, repair_action, complaint, cause, correction, "
    "vehicle {make, model, model_year}."
)


def row_from_example(text: str, target: ExtractionTarget) -> dict:
    return {
        "messages": [
            {"role": "user", "content": f"{PROMPT}\n\nTEXT:\n{text}"},
            {"role": "assistant", "content": json.dumps(target.model_dump(mode="json"), ensure_ascii=False)},
        ]
    }


async def build_training_dataset(
    repo,
    dest: Path,
    *,
    mixture_share: float = 0.0,
    dataset_version: str | None = None,
) -> dict:
    gold = await repo.list_gold()
    test_groups = {item.source_group for item in gold if item.split == "test"}
    test_ids = {item.example_id for item in gold if item.split == "test"}
    real = [item for item in gold if item.split == "train" and item.source_group not in test_groups]
    validation = [item for item in gold if item.split == "validation" and item.source_group not in test_groups]
    documents = await repo.all_documents()
    test_doc_ids = {doc.document_id for doc in documents if doc.split == "test"}
    synthetic = []
    excluded_synthetic = []
    for item in await repo.list_synthetic(limit=5000):
        if item.review_status != "approved" or item.split != "train":
            continue
        if item.source_group in test_groups or any(seed in test_doc_ids for seed in item.seed_document_ids):
            excluded_synthetic.append(item.example_id)
            continue
        synthetic.append(item)
    target_n = len(real)
    plan, reason = plan_mixture(len(real), len(synthetic), mixture_share, target_n if target_n else None)
    if mixture_share == 0 or target_n == 0:
        chosen_real = real
        chosen_syn = []
        mix_reason = reason if mixture_share else "0% synthetic uses the real train split only"
    elif plan is None:
        chosen_real = []
        chosen_syn = []
        mix_reason = reason or "mixture is not feasible"
    else:
        n_real, n_syn = plan
        chosen_real = real[:n_real]
        chosen_syn = synthetic[:n_syn]
        mix_reason = None
    train_rows = [row_from_example(item.input_text, item.target) for item in chosen_real]
    for item in chosen_syn:
        train_rows.append(row_from_example(item.input_text, item.expected_json))
    valid_rows = [row_from_example(item.input_text, item.target) for item in validation]
    leaked = [item.example_id for item in chosen_real if item.example_id in test_ids]
    if leaked or any(item.split == "test" for item in chosen_real):
        raise RuntimeError("refusing to write test-split gold into the training file")
    dest.mkdir(parents=True, exist_ok=True)
    train_path = dest / "train.jsonl"
    _write_jsonl(train_path, train_rows)
    valid_path = dest / "valid.jsonl"
    if valid_rows:
        _write_jsonl(valid_path, valid_rows)
    version = dataset_version or datetime.now(UTC).strftime("train-%Y%m%dT%H%M%SZ")
    manifest = {
        "dataset_version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "mixture_share": mixture_share,
        "mixture_reason": mix_reason,
        "train_count": len(train_rows),
        "real_train_count": len(chosen_real),
        "synthetic_train_count": len(chosen_syn),
        "validation_count": len(valid_rows),
        "test_ids_excluded": sorted(test_ids),
        "synthetic_excluded_for_leakage": excluded_synthetic,
        "train_sha256": _sha256(train_path),
        "valid_sha256": _sha256(valid_path) if valid_rows else None,
        "prompt_version": "mlx-chat-v1",
        "format": "mlx_lm messages jsonl",
        "gold_test_included": False,
    }
    (dest / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["path"] = str(dest)
    return manifest


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
