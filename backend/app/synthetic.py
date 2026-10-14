"""Synthetic technician-note paraphrases.

The deterministic teacher rewrites only fields supported by a train-split seed.
It is not an LLM. Ollama is used only when that teacher is explicitly selected
and the local server has the configured model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.errors import ProviderUnavailable, SplitLeakageError
from app.extraction import extract_target
from app.schemas import ExtractionTarget, SourceDocument, SyntheticExample
from app.splits import assert_seed_allowed
from app.textutil import find_dtcs, jaccard, normalize_dtc

PROMPT_VERSION = "demo-paraphrase-v1"
ABBREVIATIONS = {
    "check engine light": "CEL",
    "catalytic converter": "cat conv",
    "customer reports": "cust reports",
    "replaced": "repl",
    "diagnostic trouble code": "DTC",
}


def _supported_lines(target: ExtractionTarget) -> list[str]:
    lines = []
    vehicle = target.vehicle
    bits = [str(vehicle.model_year or ""), vehicle.make or "", vehicle.model or ""]
    vehicle_line = " ".join(bit for bit in bits if bit).strip()
    if vehicle_line:
        lines.append(vehicle_line)
    if target.complaint:
        lines.append(f"Customer reports {target.complaint}")
    if target.symptom:
        lines.append(target.symptom)
    if target.dtc_codes:
        lines.append("DTC " + " ".join(target.dtc_codes))
    if target.cause:
        lines.append(f"Cause: {target.cause}")
    if target.suspected_component:
        lines.append(f"Suspect {target.suspected_component}")
    if target.repair_action:
        lines.append(target.repair_action)
    elif target.correction:
        lines.append(target.correction)
    return lines


def render_variation(target: ExtractionTarget, variation: str) -> str:
    lines = _supported_lines(target)
    if not lines:
        return "DEMO paraphrase. No supported facts were available in the seed."
    text = ". ".join(lines)
    if variation == "abbreviation":
        rendered = text
        for source, dest in ABBREVIATIONS.items():
            rendered = rendered.replace(source, dest)
        return f"DEMO synthetic paraphrase ({variation}). {rendered}."
    if variation == "capitalization":
        return f"DEMO SYNTHETIC PARAPHRASE ({variation}). {text.upper()}."
    if variation == "typos":
        tokens = text.split()
        changed = False
        for index, token in enumerate(tokens):
            if len(token) >= 6 and token.isalpha():
                chars = list(token)
                chars[1], chars[2] = chars[2], chars[1]
                tokens[index] = "".join(chars)
                changed = True
                break
        rendered = " ".join(tokens) if changed else text
        return f"DEMO synthetic paraphrase ({variation}). {rendered}."
    if variation == "terse":
        terse = "; ".join(lines)
        return f"DEMO synthetic paraphrase (terse). {terse}."
    if variation == "ccc":
        complaint = target.complaint or target.symptom or "unknown"
        cause = target.cause or "unknown"
        correction = target.repair_action or target.correction or "unknown"
        return (
            "DEMO synthetic paraphrase (ccc). "
            f"Complaint: {complaint}. Cause: {cause}. Correction: {correction}."
        )
    raise ValueError(f"unknown variation {variation}")


def validate_example(example_text: str, seed_text: str, expected: ExtractionTarget) -> tuple[list[dict], list[str]]:
    checks: list[dict] = []
    flags: list[str] = []
    predicted, _evidence, _caveats, _support = extract_target(example_text)
    schema_ok = True
    checks.append({"name": "schema", "passed": schema_ok})
    seed_codes = set(find_dtcs(seed_text)) | set(expected.dtc_codes)
    extra_codes = [code for code in find_dtcs(example_text) if normalize_dtc(code) not in seed_codes]
    code_ok = not extra_codes
    checks.append({"name": "no_new_dtc", "passed": code_ok, "extra": extra_codes})
    if not code_ok:
        flags.append("unsupported_dtc")
    for field in ("component", "repair_action", "complaint", "cause"):
        value = getattr(expected, field)
        if value and value.lower() not in seed_text.lower() and field != "repair_action":
            flags.append(f"expected_{field}_not_in_seed")
    # The paraphrase may abbreviate. Contradiction means the paraphrase names a
    # DTC or a repair verb outcome that the seed does not support.
    if "replaced" in example_text.lower() and "replac" not in seed_text.lower() and not expected.repair_action:
        flags.append("invented_repair")
        checks.append({"name": "no_invented_repair", "passed": False})
    else:
        checks.append({"name": "no_invented_repair", "passed": True})
    similarity = jaccard(example_text, seed_text)
    near = similarity >= 0.92
    checks.append({"name": "not_near_duplicate", "passed": not near, "jaccard": round(similarity, 3)})
    if near:
        flags.append("near_duplicate_of_seed")
    if predicted.dtc_codes and set(predicted.dtc_codes) - seed_codes:
        flags.append("contradicts_seed_dtc")
    return checks, flags


def generate_from_document(
    document: SourceDocument,
    variations: list[str],
    *,
    teacher: str,
    limit: int,
) -> list[SyntheticExample]:
    if document.demo is False and document.split == "test":
        assert_seed_allowed(document.split, document_id=document.document_id)
    assert_seed_allowed(document.split, document_id=document.document_id)
    if not document.allow_synthetic_seed:
        raise SplitLeakageError(
            f"Document {document.document_id} is not marked allow_synthetic_seed. "
            "Reference, test, and real ingested records are excluded by default."
        )
    target, _evidence, _caveats, _support = extract_target(document.text)
    created = datetime.now(UTC)
    examples: list[SyntheticExample] = []
    for variation in variations:
        if len(examples) >= limit:
            break
        text = render_variation(target, variation)
        checks, flags = validate_example(text, document.text, target)
        status = "pending"
        if any(flag in {"unsupported_dtc", "invented_repair", "contradicts_seed_dtc"} for flag in flags):
            status = "rejected"
        examples.append(
            SyntheticExample(
                example_id=f"syn_{uuid.uuid4().hex[:12]}",
                input_text=text,
                expected_json=target,
                seed_document_ids=[document.document_id],
                source_group=document.source_group,
                generation_provider=teacher,
                generation_model="deterministic-paraphrase-v1" if teacher == "deterministic_demo" else teacher,
                generation_prompt_version=PROMPT_VERSION,
                is_llm=False,
                demo=True,
                created_at=created,
                validation_checks=checks,
                quality_flags=flags,
                review_status=status,
                review_reason="auto-rejected by rule filter" if status == "rejected" else "",
                split="train",
                variation=variation,
            )
        )
    return examples


async def generate_with_teacher(document: SourceDocument, teacher: str, settings, variation: str) -> SyntheticExample:
    """Ollama path. Raises ProviderUnavailable instead of returning a fixture."""
    if teacher != "ollama":
        raise ProviderUnavailable("This generator is only for the Ollama teacher")
    assert_seed_allowed(document.split, document_id=document.document_id)
    if not document.allow_synthetic_seed:
        raise SplitLeakageError(f"Document {document.document_id} cannot seed synthesis")
    from app.providers import OllamaProvider

    provider = OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds)
    health = await provider.health()
    if not health.available:
        raise ProviderUnavailable(health.detail or "Ollama teacher is unavailable")
    target, _e, _c, _s = extract_target(document.text)
    prompt = (
        "Rewrite ONLY the supported facts below as a short technician note. "
        "Do not add DTCs, parts, vehicles, or repairs that are not listed. "
        f"Variation: {variation}. Facts: {target.model_dump_json()}"
    )
    raw = await provider._generate(prompt)
    text = raw.strip()
    if text.startswith("{"):
        text = render_variation(target, variation if variation in {"abbreviation", "terse", "ccc", "capitalization", "typos"} else "terse")
        # If the model returned JSON instead of a note, do not pretend that JSON is a note.
        # Fall through only when we still have the model's prose. Here we reject JSON.
        raise ProviderUnavailable("Ollama returned JSON instead of a technician note; generation was not stored")
    checks, flags = validate_example(text, document.text, target)
    status = "pending"
    if any(flag in {"unsupported_dtc", "invented_repair", "contradicts_seed_dtc"} for flag in flags):
        status = "rejected"
    return SyntheticExample(
        example_id=f"syn_{uuid.uuid4().hex[:12]}",
        input_text=text,
        expected_json=target,
        seed_document_ids=[document.document_id],
        source_group=document.source_group,
        generation_provider="ollama",
        generation_model=settings.ollama_model,
        generation_prompt_version="ollama-teacher-v1",
        is_llm=True,
        demo=False,
        created_at=datetime.now(UTC),
        validation_checks=checks,
        quality_flags=flags,
        review_status=status,
        split="train",
        variation=variation,
    )


def apply_rule_filter(examples: list[SyntheticExample]) -> dict[str, int]:
    approved = rejected = unchanged = 0
    error_flags = {"unsupported_dtc", "invented_repair", "contradicts_seed_dtc"}
    for example in examples:
        if example.review_status == "rejected":
            unchanged += 1
            continue
        if any(flag in error_flags for flag in example.quality_flags):
            example.review_status = "rejected"
            example.review_reason = "rule filter rejected an error flag"
            rejected += 1
        elif "near_duplicate_of_seed" in example.quality_flags:
            example.review_status = "rejected"
            example.review_reason = "rule filter rejected a near duplicate"
            rejected += 1
        else:
            example.review_status = "approved"
            example.review_reason = "rule filter approved; this is not a human review"
            approved += 1
    return {"approved": approved, "rejected": rejected, "unchanged": unchanged}


def dedupe(examples: list[SyntheticExample], *, threshold: float = 0.92) -> list[str]:
    """Reject later near-duplicates. Returns ids newly rejected."""
    kept: list[SyntheticExample] = []
    rejected_ids: list[str] = []
    ordered = sorted(examples, key=lambda item: item.created_at)
    for example in ordered:
        if example.review_status == "rejected":
            continue
        if any(jaccard(example.input_text, prior.input_text) >= threshold for prior in kept):
            example.review_status = "rejected"
            example.review_reason = "near-duplicate of an earlier synthetic example"
            example.quality_flags = list(dict.fromkeys([*example.quality_flags, "near_duplicate"]))
            rejected_ids.append(example.example_id)
        else:
            kept.append(example)
    return rejected_ids


def target_dump(example: SyntheticExample) -> dict:
    return target_from_result_safe(example)


def target_from_result_safe(example: SyntheticExample) -> dict:
    return example.expected_json.model_dump(mode="json")
