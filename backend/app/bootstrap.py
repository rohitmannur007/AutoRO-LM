"""Load demo fixtures and rebuild the retrieval index."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.ingestion import chunks_for_document
from app.retrieval import RetrievalIndex
from app.schemas import GoldExample, SourceDocument
from app.textutil import checksum, find_dtcs

DEMO_LICENSE = (
    "Hand-authored demonstration text. Not an official NHTSA record, TSB, or repair order."
)


async def load_demo_fixtures(repo, demo_dir: Path, *, force: bool = False) -> dict:
    if not force:
        counts = await repo.count_documents()
        if counts["documents"]:
            return {"status": "skipped", "reason": "documents already present", **counts}
    if force:
        await repo.clear_all()
    doc_payload = json.loads((demo_dir / "documents.json").read_text(encoding="utf-8"))
    gold_payload = json.loads((demo_dir / "gold_examples.json").read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    loaded = 0
    for raw in doc_payload["documents"]:
        text = raw["text"].strip()
        document = SourceDocument(
            document_id=raw["document_id"],
            source_type=raw["source_type"],
            source_url=None,
            source_name=raw["source_name"],
            retrieved_at=now,
            published_at=None,
            license_notes=DEMO_LICENSE,
            make=raw.get("make"),
            model=raw.get("model"),
            model_year=raw.get("model_year"),
            component=raw.get("component"),
            dtc_codes=find_dtcs(text),
            text=text,
            raw_text=text,
            checksum=checksum(text),
            provenance={
                "label": "DEMO",
                "origin": "hand_authored_fixture",
                "not_nhtsa": True,
                "pack": "backend/data/demo/documents.json",
            },
            ingestion_status="loaded",
            demo=True,
            source_group=raw["source_group"],
            split=raw["split"],
            allow_synthetic_seed=bool(raw.get("allow_synthetic_seed")),
            narrative_kind=raw.get("narrative_kind", "demo_note"),
            metadata={"fixture_label": doc_payload.get("label", "DEMO")},
        )
        await repo.upsert_document(document)
        await repo.replace_chunks(document.document_id, chunks_for_document(document))
        loaded += 1
    gold_loaded = 0
    for raw in gold_payload["examples"]:
        example = GoldExample(
            example_id=raw["example_id"],
            source_document_ids=raw.get("source_document_ids") or [],
            source_group=raw["source_group"],
            input_text=raw["input_text"],
            target=raw.get("target") or {},
            component_category=raw.get("component_category"),
            annotation_guideline_version=gold_payload.get("guideline_version", "1.0.0"),
            reviewer_notes=raw.get("reviewer_notes", ""),
            split=raw["split"],
            created_at=now,
            demo=True,
        )
        await repo.save_gold(example)
        gold_loaded += 1
    await repo.add_audit("load_demo_fixtures", {"documents": loaded, "gold": gold_loaded, "label": "DEMO"})
    return {"status": "loaded", "documents": loaded, "gold": gold_loaded, "label": "DEMO"}


async def rebuild_index(repo) -> RetrievalIndex:
    index = RetrievalIndex()
    index.build(await repo.all_documents(), await repo.all_chunks())
    return index


def load_qa_labels(demo_dir: Path) -> list[dict]:
    payload = json.loads((demo_dir / "qa_labels.json").read_text(encoding="utf-8"))
    return list(payload.get("questions") or [])
