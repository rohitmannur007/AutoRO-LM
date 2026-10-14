"""Adopt a model's JSON extraction without copying the rules baseline into it.

Unsupported strings and DTCs that do not occur in the source are dropped.
They are not replaced with rule-extractor values. A DTC is not treated as
proof that a component failed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.extraction import unknown_fields
from app.schemas import (
    EvidenceSpan,
    ExtractionResult,
    ExtractionTarget,
    ProviderMetadata,
    VehicleInfo,
)
from app.textutil import find_dtcs, find_span, normalize_whitespace, tokenize

PROMPT_VERSION = "model-extract-v1"
STRING_FIELDS = (
    "symptom",
    "component",
    "suspected_component",
    "repair_action",
    "complaint",
    "cause",
    "correction",
)
SUBSTRING_ONLY = {"component", "suspected_component", "repair_action", "cause", "correction"}


def adopt_model_extraction(
    text: str,
    payload: dict,
    vehicle: VehicleInfo | None,
    *,
    provider_name: str,
    model: str | None,
    prompt_version: str = PROMPT_VERSION,
) -> ExtractionResult:
    if not isinstance(payload, dict):
        raise ValueError("model extraction payload must be a JSON object")
    normalized = normalize_whitespace(text)
    dropped: list[str] = []
    support: dict[str, str] = {}
    evidence: list[EvidenceSpan] = []
    values: dict[str, str | None] = {}

    for field in STRING_FIELDS:
        kept, status = _keep_string(field, payload.get(field), normalized)
        values[field] = kept
        support[field] = status
        if status == "rejected_unsupported":
            dropped.append(field)
        elif kept and status == "model_literal":
            span = find_span(normalized, kept)
            evidence.append(
                EvidenceSpan(
                    field_name=field,
                    quoted_text=kept,
                    start=None if span is None else span[0],
                    end=None if span is None else span[1],
                    evidence_type="model_literal",
                    support_status="supported",
                )
            )

    codes, rejected_codes = _keep_dtcs(payload.get("dtc_codes"), normalized)
    dropped.extend(rejected_codes)
    support["dtc_codes"] = "model_literal" if codes else "absent" if not payload.get("dtc_codes") else "rejected_unsupported"

    if values["component"] and _suspect_cue(normalized) and values["component"].lower() in normalized.lower():
        if not values["suspected_component"]:
            values["suspected_component"] = values["component"]
            support["suspected_component"] = "moved_from_component"
        values["component"] = None
        support["component"] = "not_confirmed"
        dropped.append("component_not_confirmed")

    parsed_vehicle, vehicle_dropped = _keep_vehicle(payload.get("vehicle"), normalized, vehicle)
    dropped.extend(vehicle_dropped)
    target = ExtractionTarget(
        symptom=values["symptom"],
        dtc_codes=codes,
        component=values["component"],
        suspected_component=values["suspected_component"],
        repair_action=values["repair_action"],
        complaint=values["complaint"],
        cause=values["cause"],
        correction=values["correction"],
        vehicle=parsed_vehicle,
    )
    caveats = [
        "prediction_source=model. Fields that are not supported by the source text were dropped.",
        "The rules extractor was not used to fill this result.",
        "A diagnostic trouble code is not proof that a component failed.",
    ]
    if any(item.startswith("dtc:") for item in dropped):
        caveats.append("One or more DTC values were rejected because they do not occur in the source text.")
    return ExtractionResult(
        extraction_id=f"ex_{uuid.uuid4().hex[:12]}",
        symptom=target.symptom,
        dtc_codes=target.dtc_codes,
        component=target.component,
        suspected_component=target.suspected_component,
        repair_action=target.repair_action,
        complaint=target.complaint,
        cause=target.cause,
        correction=target.correction,
        unknown_fields=unknown_fields(target),
        evidence=evidence,
        vehicle=target.vehicle,
        provider=ProviderMetadata(
            provider=provider_name,
            model=model,
            is_llm=True,
            demo=False,
            prompt_version=prompt_version,
            caveats=caveats,
        ),
        created_at=datetime.now(UTC),
        demo=False,
        schema_valid=True,
        validation_errors=[f"unsupported field dropped: {item}" for item in dropped],
        field_support=support,
    )


def _keep_string(field: str, value, text: str) -> tuple[str | None, str]:
    if value is None or (isinstance(value, str) and value.strip().lower() in {"", "null", "none", "unknown", "n/a"}):
        return None, "absent"
    if not isinstance(value, str):
        return None, "rejected_unsupported"
    cleaned = " ".join(value.split())
    if cleaned.lower() in text.lower():
        return cleaned, "model_literal"
    if field in SUBSTRING_ONLY:
        return None, "rejected_unsupported"
    content = [token for token in tokenize(cleaned) if len(token) >= 4]
    if content and any(token in text.lower() for token in content):
        return cleaned, "model_normalized"
    return None, "rejected_unsupported"


def _keep_dtcs(value, text: str) -> tuple[list[str], list[str]]:
    present = set(find_dtcs(text))
    kept: list[str] = []
    dropped: list[str] = []
    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], ["dtc_codes"]
    for item in value:
        found = find_dtcs(str(item))
        if not found:
            dropped.append(f"dtc:{item}")
            continue
        for code in found:
            if code in present:
                if code not in kept:
                    kept.append(code)
            else:
                dropped.append(f"dtc:{code}")
    return kept, dropped


def _keep_vehicle(payload, text: str, hint: VehicleInfo | None) -> tuple[VehicleInfo, list[str]]:
    hint = hint or VehicleInfo()
    raw = payload if isinstance(payload, dict) else {}
    dropped: list[str] = []
    make = _vehicle_text("make", raw.get("make"), text, hint.make)
    model = _vehicle_text("model", raw.get("model"), text, hint.model)
    year = _vehicle_year(raw.get("model_year"), text, hint.model_year)
    if raw.get("make") and make is None:
        dropped.append("vehicle.make")
    if raw.get("model") and model is None:
        dropped.append("vehicle.model")
    if raw.get("model_year") not in (None, "", "null") and year is None:
        dropped.append("vehicle.model_year")
    return VehicleInfo(make=make, model=model, model_year=year), dropped


def _vehicle_text(field: str, value, text: str, hint: str | None) -> str | None:
    del field
    if not isinstance(value, str) or not value.strip():
        return hint
    cleaned = value.strip()
    if cleaned.lower() in text.lower():
        return cleaned
    if hint and hint.lower() == cleaned.lower():
        return hint
    return None


def _vehicle_year(value, text: str, hint: int | None) -> int | None:
    if value in (None, "", "null"):
        return hint
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if str(year) in text or hint == year:
        if 1980 <= year <= 2035:
            return year
    return None


def _suspect_cue(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in ("suspect", "possible", "may be", "could be"))
