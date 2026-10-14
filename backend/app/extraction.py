"""Transparent rules baseline for repair-note extraction.

The extractor copies only spans supported by the input text. A DTC catalog is
not used to fill component fields: a code is not treated as a failed part.
"""

import re
import uuid
from datetime import UTC, datetime

from app.schemas import (
    EvidenceSpan,
    ExtractionResult,
    ExtractionTarget,
    ProviderMetadata,
    VehicleInfo,
)
from app.textutil import (
    COMPONENT_ALIASES,
    MAKE_ALIASES,
    MODEL_PAIRS,
    REPAIR_VERBS,
    YEAR_RE,
    find_dtcs,
    find_span,
    normalize_whitespace,
)

SYMPTOM_PATTERNS: list[tuple[str, str]] = [
    (r"check engine light|cel\b|malfunction indicator", "check engine light"),
    (r"rotten egg smell", "rotten egg smell"),
    (r"rough idle", "rough idle"),
    (r"no(?:t|t going to)? start|won't start|will not start", "no-start"),
    (r"grind(?:ing)?(?: from| at| noise)?", "grind"),
    (r"brake pedal pulsates|pulsat\w+ brake", "brake pedal pulsation"),
    (r"pulls? to the (?:left|right)", "pull"),
    (r"overheat(?:ing)?", "overheating"),
    (r"not cold|isn't cold|is not cold|no cold air", "air conditioning not cold"),
    (r"dead after|battery is dead|dead battery", "dead battery"),
    (r"will not shift|won't shift|not shift", "will not shift"),
    (r"vibrat(?:e|ion|ing)", "vibration"),
    (r"stall(?:s|ing|ed)?", "stalling"),
]

SUSPECT_RE = re.compile(
    r"\b(?:suspect(?:ed)?|possible|possibly|likely|may be)\b(?:\s+a|\s+an|\s+the)?\s+"
    r"([a-z0-9][a-z0-9 \-/]{2,40})",
    re.IGNORECASE,
)
FAILED_RE = re.compile(
    r"\b(?:failed|faulty|bad|inoperative)\s+([a-z0-9][a-z0-9 \-/]{2,40})",
    re.IGNORECASE,
)
REPAIR_RE = re.compile(
    r"\b(" + "|".join(REPAIR_VERBS) + r")\b\s+(?:the\s+|a\s+|an\s+)?([a-z0-9][a-z0-9 \-/]{2,48})",
    re.IGNORECASE,
)
COMPLAINT_RE = re.compile(
    r"\b(?:customer|cust\.?|owner)\s+(?:reports?|states?|complains?|says)\s+([^.]+)",
    re.IGNORECASE,
)
CAUSE_RE = re.compile(r"\b(?:caused by|due to|cause:)\s+([^.]+)", re.IGNORECASE)
CCC_RE = {
    "complaint": re.compile(r"(?:^|\n)\s*complaint\s*:\s*(.+)", re.IGNORECASE),
    "cause": re.compile(r"(?:^|\n)\s*cause\s*:\s*(.+)", re.IGNORECASE),
    "correction": re.compile(r"(?:^|\n)\s*correction\s*:\s*(.+)", re.IGNORECASE),
}

DTC_NOT_PROOF = (
    "A diagnostic trouble code by itself is not proof that a component has failed."
)


def _clean_phrase(phrase: str) -> str:
    phrase = re.sub(r"\s+", " ", phrase).strip(" .,:;-")
    phrase = re.split(r"\b(?:and|then|after|before)\b", phrase, maxsplit=1, flags=re.IGNORECASE)[0]
    return phrase.strip(" .,:;-")


def _canonical_component(phrase: str) -> str:
    cleaned = _clean_phrase(phrase).lower()
    cleaned = re.sub(r"^(the|a|an)\s+", "", cleaned)
    for alias, canonical in sorted(COMPONENT_ALIASES.items(), key=lambda item: -len(item[0])):
        if alias in cleaned:
            return canonical
    return cleaned


def _vehicle_from_text(text: str, hint: VehicleInfo | None) -> tuple[VehicleInfo, list[EvidenceSpan]]:
    evidence: list[EvidenceSpan] = []
    make = hint.make if hint and hint.make else None
    model = hint.model if hint and hint.model else None
    year = hint.model_year if hint and hint.model_year else None
    vin = hint.vin if hint else None

    if make is None:
        for alias, canonical in MAKE_ALIASES.items():
            match = re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE)
            if match:
                make = canonical
                evidence.append(
                    EvidenceSpan(
                        field_name="vehicle.make",
                        quoted_text=text[match.start() : match.end()],
                        start=match.start(),
                        end=match.end(),
                    )
                )
                break
    if model is None:
        for pair_make, needle, canonical in MODEL_PAIRS:
            if make and pair_make != make:
                continue
            match = re.search(rf"\b{re.escape(needle)}\b", text, re.IGNORECASE)
            if match:
                model = canonical
                if make is None:
                    make = pair_make
                evidence.append(
                    EvidenceSpan(
                        field_name="vehicle.model",
                        quoted_text=text[match.start() : match.end()],
                        start=match.start(),
                        end=match.end(),
                    )
                )
                break
    if year is None:
        match = YEAR_RE.search(text)
        if match:
            year = int(match.group(1))
            evidence.append(
                EvidenceSpan(
                    field_name="vehicle.model_year",
                    quoted_text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                )
            )
    return VehicleInfo(make=make, model=model, model_year=year, vin=vin), evidence


def _span(field: str, quote: str, text: str, *, evidence_type: str = "literal") -> EvidenceSpan | None:
    found = find_span(text, quote)
    if not found:
        return None
    start, end = found
    return EvidenceSpan(
        field_name=field,
        quoted_text=text[start:end],
        start=start,
        end=end,
        evidence_type=evidence_type,
        support_status="supported" if evidence_type == "literal" else "partial",
    )


def extract_target(text: str, vehicle: VehicleInfo | None = None) -> tuple[ExtractionTarget, list[EvidenceSpan], list[str], dict[str, str]]:
    """Return a target, evidence, caveats, and field support labels."""
    raw = text or ""
    cleaned = normalize_whitespace(raw)
    evidence: list[EvidenceSpan] = []
    caveats: list[str] = []
    support: dict[str, str] = {}

    vehicle_info, vehicle_evidence = _vehicle_from_text(cleaned, vehicle)
    evidence.extend(vehicle_evidence)

    dtcs = find_dtcs(cleaned)
    for code in dtcs:
        match = re.search(rf"\b{code[0]}[\s\-]?{code[1:]}\b", cleaned, re.IGNORECASE)
        if match:
            evidence.append(
                EvidenceSpan(
                    field_name="dtc_codes",
                    quoted_text=cleaned[match.start() : match.end()],
                    start=match.start(),
                    end=match.end(),
                )
            )
    if dtcs:
        caveats.append(DTC_NOT_PROOF)
        support["dtc_codes"] = "supported"
    else:
        support["dtc_codes"] = "unknown"

    symptom = None
    for pattern, label in SYMPTOM_PATTERNS:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            symptom = label
            evidence.append(
                EvidenceSpan(
                    field_name="symptom",
                    quoted_text=cleaned[match.start() : match.end()],
                    start=match.start(),
                    end=match.end(),
                )
            )
            break
    support["symptom"] = "supported" if symptom else "unknown"

    complaint = None
    complaint_match = COMPLAINT_RE.search(cleaned) or CCC_RE["complaint"].search(cleaned)
    if complaint_match:
        complaint = _clean_phrase(complaint_match.group(1))
        span = _span("complaint", complaint_match.group(1).strip(), cleaned)
        if span:
            evidence.append(span)
    support["complaint"] = "supported" if complaint else "unknown"

    cause = None
    cause_match = CCC_RE["cause"].search(cleaned) or CAUSE_RE.search(cleaned)
    if cause_match:
        cause_text = _clean_phrase(cause_match.group(1))
        if cause_text.lower() not in {"unknown", "n/a", "na", "not stated"}:
            cause = cause_text
            span = _span("cause", cause_match.group(1).strip(), cleaned)
            if span:
                evidence.append(span)
    support["cause"] = "supported" if cause else "unknown"

    correction = None
    correction_match = CCC_RE["correction"].search(cleaned)
    if correction_match:
        correction = _clean_phrase(correction_match.group(1))
        if correction.lower() in {"unknown", "none", "n/a"}:
            correction = None
        else:
            span = _span("correction", correction_match.group(1).strip(), cleaned)
            if span:
                evidence.append(span)

    repair_action = None
    component = None
    repair_match = REPAIR_RE.search(cleaned)
    if repair_match:
        verb = repair_match.group(1).lower()
        part = _canonical_component(repair_match.group(2))
        repair_action = f"{verb} {part}"
        component = part
        span = _span("repair_action", repair_match.group(0), cleaned)
        if span:
            evidence.append(span)
        span = _span("component", repair_match.group(2), cleaned)
        if span:
            evidence.append(span)
    if correction and repair_action is None:
        repair_action = correction
    support["repair_action"] = "supported" if repair_action else "unknown"
    support["correction"] = "supported" if correction or repair_action else "unknown"
    if correction is None and repair_action:
        correction = repair_action

    suspected = None
    suspect_match = SUSPECT_RE.search(cleaned)
    if suspect_match:
        suspected = _canonical_component(suspect_match.group(1))
        span = _span("suspected_component", suspect_match.group(0), cleaned, evidence_type="linguistic_cue")
        if span:
            evidence.append(span)
    failed_match = FAILED_RE.search(cleaned)
    if failed_match and component is None and suspect_match is None:
        # "failed X" names a part the writer asserts. Keep it as suspected unless
        # a completed repair also names it. The writer asserted failure; we still
        # do not upgrade a DTC-only mention.
        component = _canonical_component(failed_match.group(1))
        span = _span("component", failed_match.group(0), cleaned)
        if span:
            evidence.append(span)
    if suspected and component and suspected == component:
        suspected = None
    support["component"] = "supported" if component else "unknown"
    support["suspected_component"] = "partial" if suspected else "unknown"
    support["vehicle.make"] = "supported" if vehicle_info.make else "unknown"
    support["vehicle.model"] = "supported" if vehicle_info.model else "unknown"
    support["vehicle.model_year"] = "supported" if vehicle_info.model_year else "unknown"

    target = ExtractionTarget(
        symptom=symptom,
        dtc_codes=dtcs,
        component=component,
        suspected_component=suspected,
        repair_action=repair_action,
        complaint=complaint,
        cause=cause,
        correction=correction,
        vehicle=vehicle_info,
    )
    return target, evidence, caveats, support


def unknown_fields(target: ExtractionTarget) -> list[str]:
    missing: list[str] = []
    if not target.symptom:
        missing.append("symptom")
    if not target.dtc_codes:
        missing.append("dtc_codes")
    if not target.component:
        missing.append("component")
    if not target.suspected_component:
        missing.append("suspected_component")
    if not target.repair_action:
        missing.append("repair_action")
    if not target.complaint:
        missing.append("complaint")
    if not target.cause:
        missing.append("cause")
    if not target.correction:
        missing.append("correction")
    if not target.vehicle.make:
        missing.append("vehicle.make")
    if not target.vehicle.model:
        missing.append("vehicle.model")
    if not target.vehicle.model_year:
        missing.append("vehicle.model_year")
    return missing


def extract_rules(
    text: str,
    vehicle: VehicleInfo | None = None,
    *,
    provider_name: str = "deterministic_demo",
    demo: bool = True,
    is_llm: bool = False,
    model: str | None = "rules-v1",
) -> ExtractionResult:
    target, evidence, caveats, support = extract_target(text, vehicle)
    normalized = normalize_whitespace(text)
    errors: list[str] = []
    for span in evidence:
        if span.quoted_text and find_span(normalized, span.quoted_text) is None:
            errors.append(f"evidence for {span.field_name} is not a substring")
    result = ExtractionResult(
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
            is_llm=is_llm,
            demo=demo,
            prompt_version=None if not is_llm else "n/a",
            caveats=caveats,
        ),
        created_at=datetime.now(UTC),
        demo=demo,
        schema_valid=not errors,
        validation_errors=errors,
        field_support=support,
    )
    return result


def target_from_result(result: ExtractionResult) -> ExtractionTarget:
    return ExtractionTarget(
        symptom=result.symptom,
        dtc_codes=list(result.dtc_codes),
        component=result.component,
        suspected_component=result.suspected_component,
        repair_action=result.repair_action,
        complaint=result.complaint,
        cause=result.cause,
        correction=result.correction,
        vehicle=result.vehicle,
    )
