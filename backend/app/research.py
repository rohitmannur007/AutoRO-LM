"""Real-data splits and an explicit train-only synthetic eligibility step."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.errors import AppError, SplitLeakageError
from app.schemas import GoldExample
from app.splits import assign_group_splits, group_key

ENABLE_CONFIRM = "ENABLE_TRAIN_SEEDS"


async def assign_complaint_splits(repo, dest: Path, *, seed: int = 42) -> dict:
    documents = await repo.all_documents()
    complaints = [doc for doc in documents if doc.source_type == "nhtsa_complaint" and not doc.demo]
    groups = []
    for doc in complaints:
        # Vehicle identity is the split group. A per-complaint id would let
        # one make/model/year appear in both train and test.
        key = group_key(doc.make, doc.model, doc.model_year)
        doc.source_group = key
        groups.append(key)
    mapping = assign_group_splits(groups, seed=seed) if groups else {}
    counts = {"train": 0, "validation": 0, "test": 0, "reference": 0}
    for doc in complaints:
        doc.split = mapping[doc.source_group]
        doc.allow_synthetic_seed = False
        await repo.upsert_document(doc)
        counts[doc.split] = counts.get(doc.split, 0) + 1
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "scope": "nhtsa_complaint",
        "group_to_split": mapping,
        "counts": counts,
        "complaint_documents": len(complaints),
        "note": (
            "Groups are make|model|year. Recalls and manufacturer communications stay in the "
            "reference split and are not training seeds. allow_synthetic_seed stays false until "
            "an explicit eligibility call."
        ),
        "validation_available": "validation" in mapping.values(),
        "fallback": "With fewer than 3 groups, validation may be absent. See assign_group_splits.",
    }
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"split-manifest-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["path"] = str(path)
    await repo.add_audit("assign_splits", {"complaints": len(complaints), "seed": seed, "path": str(path)})
    return manifest


async def enable_train_seeds(repo, *, confirm: str, document_ids: list[str] | None = None) -> dict:
    if confirm != ENABLE_CONFIRM:
        raise AppError(f"Confirmation text must be {ENABLE_CONFIRM}")
    wanted = set(document_ids or [])
    enabled: list[str] = []
    refused: list[dict] = []
    for doc in await repo.all_documents():
        if wanted and doc.document_id not in wanted:
            continue
        if not wanted and doc.demo:
            continue
        if doc.split != "train":
            if wanted:
                refused.append({"document_id": doc.document_id, "reason": f"split is {doc.split}"})
            continue
        if doc.source_type in {"nhtsa_recall", "nhtsa_mfr_comm"}:
            refused.append({"document_id": doc.document_id, "reason": "reference document"})
            continue
        doc.allow_synthetic_seed = True
        await repo.upsert_document(doc)
        enabled.append(doc.document_id)
    await repo.add_audit("enable_train_seeds", {"enabled": len(enabled), "refused": len(refused)})
    return {"enabled": enabled, "refused": refused, "enabled_count": len(enabled)}


async def save_gold_example(repo, example: GoldExample) -> GoldExample:
    for document_id in example.source_document_ids:
        document = await repo.get_document(document_id)
        if document is None:
            continue
        if document.split == "test" and example.split != "test":
            raise SplitLeakageError(
                f"Gold example {example.example_id} cannot use test document {document_id} outside the test split."
            )
        if document.split in {"train", "validation"} and example.split != document.split:
            raise SplitLeakageError(
                f"Gold example {example.example_id} split {example.split} does not match document {document_id} split {document.split}."
            )
    if example.split == "test":
        example_groups = {example.source_group}
        train_groups = {item.source_group for item in await repo.list_gold(split="train")}
        if example.source_group in train_groups:
            raise SplitLeakageError(
                f"Source group {example.source_group} is already in train. Refusing to also place it in test."
            )
        del example_groups
    await repo.save_gold(example)
    return example
