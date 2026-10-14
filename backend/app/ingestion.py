"""Public-source ingestion.

Live endpoints were checked on 2026-10-13:
- complaints: https://api.nhtsa.gov/complaints/complaintsByVehicle
- recalls: https://api.nhtsa.gov/recalls/recallsByVehicle
- manufacturer communications JSON paths returned HTTP 403. The supported
  path is the official flat-file ZIP/CSV described in TSBS.txt.

Parsers accept the field names observed that day and fail closed when the
required keys are absent. VINs from complaints are dropped.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.schemas import DocumentChunk, SourceDocument
from app.splits import group_key
from app.textutil import checksum, chunk_text, find_dtcs, normalize_whitespace

NHTSA_COMPLAINTS_URL = "https://api.nhtsa.gov/complaints/complaintsByVehicle"
NHTSA_RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"
NHTSA_MFR_CSV_URL = "https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2025-2026.zip"
NHTSA_DOCS_URL = "https://www.nhtsa.gov/nhtsa-datasets-and-apis"
ACCESS_DATE = "2026-10-13"
USER_AGENT = "AutoRO-LM/0.1 (local research prototype)"

COMPLAINT_REQUIRED = ("odinumber", "summary")
RECALL_REQUIRED = ("nhtsacampaignnumber", "summary")
MFR_REQUIRED = ("tsb/document id", "concise summary")


class IngestionFormatError(ValueError):
    pass


def _pick(row: dict, *names: str):
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _results(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        raise IngestionFormatError("expected a JSON object")
    results = payload.get("results", payload.get("Results"))
    if not isinstance(results, list):
        raise IngestionFormatError("JSON object has no results list; schema may have drifted")
    return [row for row in results if isinstance(row, dict)]


def _require_fields(row: dict, required: tuple[str, ...], kind: str) -> None:
    lowered = {str(key).lower() for key in row}
    missing = [name for name in required if name not in lowered]
    if missing:
        raise IngestionFormatError(f"{kind} record missing required fields {missing}")


def _year(value) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "9999" or "," in text:
        return None
    if text.isdigit() and len(text) == 4:
        year = int(text)
        return year if 1980 <= year <= 2035 else None
    return None


def _years(value) -> list[int]:
    if value is None:
        return []
    years = []
    for part in str(value).split(","):
        year = _year(part.strip())
        if year:
            years.append(year)
    return years


def parse_complaint_payload(payload: dict, *, retrieved_at: datetime, max_records: int) -> list[SourceDocument]:
    docs = []
    for row in _results(payload)[:max_records]:
        _require_fields(row, COMPLAINT_REQUIRED, "complaint")
        odi = str(_pick(row, "odiNumber")).strip()
        summary = normalize_whitespace(str(_pick(row, "summary") or ""))
        if not summary:
            continue
        products = _pick(row, "products") or []
        product = products[0] if isinstance(products, list) and products else {}
        if not isinstance(product, dict):
            product = {}
        make = _pick(product, "productMake") or None
        model = _pick(product, "productModel") or None
        year = _year(_pick(product, "productYear"))
        component = _pick(row, "components")
        if isinstance(component, list):
            component = ", ".join(str(item) for item in component)
        raw = summary
        text = (
            f"NHTSA consumer complaint {odi}. This is a consumer narrative, not a confirmed repair order. "
            f"{summary}"
        )
        docs.append(
            _document(
                document_id=f"nhtsa-complaint-{odi}",
                source_type="nhtsa_complaint",
                source_url=f"https://www.nhtsa.gov/vehicle/{(make or '').lower()}/{(model or '').lower()}/{year or ''}/complaints",
                source_name=f"NHTSA complaint {odi}",
                retrieved_at=retrieved_at,
                published_at=str(_pick(row, "dateComplaintFiled") or "") or None,
                make=str(make).title() if make else None,
                model=str(model).title() if model else None,
                model_year=year,
                component=str(component) if component else None,
                text=text,
                raw_text=raw,
                narrative_kind="consumer_complaint",
                provenance={
                    "agency": "NHTSA",
                    "endpoint": NHTSA_COMPLAINTS_URL,
                    "documentation_url": NHTSA_DOCS_URL,
                    "access_date": ACCESS_DATE,
                    "odi_number": odi,
                    "vin_stored": False,
                    "terms": "US federal public data. Not for bulk VIN lookup. See https://api.nhtsa.gov/",
                },
                metadata={"manufacturer": _pick(row, "manufacturer"), "crash": _pick(row, "crash"), "fire": _pick(row, "fire")},
                demo=False,
                allow_synthetic_seed=False,
                split="train",
                source_group=group_key(str(make) if make else None, str(model) if model else None, year),
            )
        )
    return docs


def parse_recall_payload(payload: dict, *, retrieved_at: datetime, max_records: int) -> list[SourceDocument]:
    docs = []
    for row in _results(payload)[:max_records]:
        _require_fields(row, RECALL_REQUIRED, "recall")
        campaign = str(_pick(row, "NHTSACampaignNumber")).strip()
        summary = normalize_whitespace(str(_pick(row, "Summary") or ""))
        remedy = normalize_whitespace(str(_pick(row, "Remedy") or ""))
        consequence = normalize_whitespace(str(_pick(row, "Consequence") or ""))
        text = (
            f"NHTSA recall campaign {campaign}. This is a recall summary, not a shop repair order. "
            f"Summary: {summary} Consequence: {consequence} Remedy: {remedy}"
        )
        make = _pick(row, "Make")
        model = _pick(row, "Model")
        year = _year(_pick(row, "ModelYear"))
        docs.append(
            _document(
                document_id=f"nhtsa-recall-{campaign}-{(make or 'unk').lower()}-{(model or 'unk').lower()}-{year or 'na'}",
                source_type="nhtsa_recall",
                source_url=f"https://www.nhtsa.gov/recalls?nhtsaId={campaign}",
                source_name=f"NHTSA recall {campaign}",
                retrieved_at=retrieved_at,
                published_at=str(_pick(row, "ReportReceivedDate") or "") or None,
                make=str(make).title() if make else None,
                model=str(model).title() if model else None,
                model_year=year,
                component=str(_pick(row, "Component") or "") or None,
                text=normalize_whitespace(text),
                raw_text=summary,
                narrative_kind="recall",
                provenance={
                    "agency": "NHTSA",
                    "endpoint": NHTSA_RECALLS_URL,
                    "documentation_url": NHTSA_DOCS_URL,
                    "access_date": ACCESS_DATE,
                    "campaign_number": campaign,
                    "terms": "US federal public data. See https://api.nhtsa.gov/",
                },
                metadata={"park_it": _pick(row, "parkIt"), "park_outside": _pick(row, "parkOutSide")},
                demo=False,
                allow_synthetic_seed=False,
                split="reference",
                source_group=f"recall|{campaign}",
            )
        )
    return docs


def parse_mfr_csv(text: str, *, retrieved_at: datetime, source_url: str, max_records: int) -> list[SourceDocument]:
    sample = text.lstrip("\ufeff")
    try:
        reader = csv.DictReader(io.StringIO(sample))
    except csv.Error as exc:
        raise IngestionFormatError(f"CSV parse failed: {exc}") from exc
    if not reader.fieldnames:
        raise IngestionFormatError("manufacturer communications file has no header")
    lowered = [name.lower().strip() for name in reader.fieldnames]
    if "tsb/document id" not in lowered or not ({"concise summary", "summary"} & set(lowered)):
        raise IngestionFormatError(
            f"unexpected manufacturer communications columns: {reader.fieldnames}. "
            "Refusing to guess a drifted schema."
        )
    docs = []
    for row in reader:
        if len(docs) >= max_records:
            break
        doc_id = str(_pick(row, "TSB/Document ID") or "").strip()
        summary = normalize_whitespace(str(_pick(row, "Concise Summary", "Summary") or ""))
        if not doc_id or not summary:
            continue
        make = _pick(row, "Make")
        model = _pick(row, "Model")
        years = _years(_pick(row, "Model Year"))
        year = years[0] if len(years) == 1 else None
        text_out = (
            "NHTSA manufacturer communication concise summary. This is not a full service manual "
            f"and not a confirmed repair order. Document {doc_id}. {summary}"
        )
        docs.append(
            _document(
                document_id=f"nhtsa-mfr-{doc_id}-{(make or 'unk').lower()}-{(model or 'unk').lower()}-{year or 'multi'}",
                source_type="nhtsa_mfr_comm",
                source_url=source_url,
                source_name=f"NHTSA manufacturer communication {doc_id}",
                retrieved_at=retrieved_at,
                published_at=None,
                make=str(make).title() if make else None,
                model=str(model).title() if model else None,
                model_year=year,
                component=None,
                text=text_out,
                raw_text=summary,
                narrative_kind="manufacturer_communication",
                provenance={
                    "agency": "NHTSA",
                    "file_dictionary": "https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS.txt",
                    "documentation_url": NHTSA_DOCS_URL,
                    "access_date": ACCESS_DATE,
                    "document_id": doc_id,
                    "model_years": years,
                    "terms": "US federal public data published as flat files. JSON communications API was not available (HTTP 403 on 2026-10-13).",
                },
                metadata={"all_model_years": years},
                demo=False,
                allow_synthetic_seed=False,
                split="reference",
                source_group=f"mfr|{doc_id}",
            )
        )
    return docs


def chunks_for_document(document: SourceDocument) -> list[DocumentChunk]:
    chunks = []
    for index, (start, end, text) in enumerate(chunk_text(document.text)):
        chunks.append(
            DocumentChunk(
                chunk_id=f"{document.document_id}:c{index}",
                document_id=document.document_id,
                chunk_index=index,
                text=text,
                start_offset=start,
                end_offset=end,
                metadata={
                    "source_type": document.source_type,
                    "demo": document.demo,
                    "make": document.make,
                    "model": document.model,
                    "model_year": document.model_year,
                },
                embedding_status="tfidf_on_index",
            )
        )
    return chunks


def safe_zip_csv(payload: bytes, *, max_uncompressed: int) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise IngestionFormatError("download is not a valid zip archive") from exc
    infos = archive.infolist()
    if len(infos) > 20:
        raise IngestionFormatError("archive has too many members")
    chosen = None
    for info in infos:
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise IngestionFormatError(f"unsafe archive path: {name}")
        if info.file_size > max_uncompressed:
            raise IngestionFormatError("archive member exceeds size cap")
        if name.lower().endswith(".csv"):
            chosen = info
            break
    if chosen is None:
        raise IngestionFormatError("archive contains no CSV member")
    data = archive.read(chosen)
    if len(data) > max_uncompressed:
        raise IngestionFormatError("uncompressed CSV exceeds size cap")
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestionFormatError("CSV encoding could not be decoded")


async def fetch_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    response = await client.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise IngestionFormatError(f"unexpected content type {content_type}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise IngestionFormatError("JSON root is not an object")
    return payload


async def download_bytes(client: httpx.AsyncClient, url: str, *, max_bytes: int) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"https"}:
        raise IngestionFormatError("only https downloads are allowed")
    host = parsed.netloc.lower()
    if host not in {"static.nhtsa.gov", "api.nhtsa.gov"}:
        raise IngestionFormatError(f"host {host} is not in the allow list")
    hasher = hashlib.sha256()
    buffer = io.BytesIO()
    async with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        async for part in response.aiter_bytes():
            if buffer.tell() + len(part) > max_bytes:
                raise IngestionFormatError(f"download exceeded {max_bytes} bytes")
            buffer.write(part)
            hasher.update(part)
    return buffer.getvalue(), hasher.hexdigest()


def _document(**kwargs) -> SourceDocument:
    text = kwargs["text"]
    kwargs["checksum"] = checksum(text)
    kwargs["dtc_codes"] = find_dtcs(text)
    kwargs.setdefault("license_notes", "Public US government data. See provenance.")
    kwargs.setdefault("ingestion_status", "loaded")
    return SourceDocument(**kwargs)


def profile_documents(documents: list[SourceDocument]) -> dict:
    from collections import Counter

    from app.textutil import histogram

    lengths = [len(doc.text) for doc in documents]
    dtcs: Counter[str] = Counter()
    components: Counter[str] = Counter()
    missing_make = 0
    kinds: Counter[str] = Counter()
    for doc in documents:
        dtcs.update(doc.dtc_codes)
        if doc.component:
            components[doc.component] += 1
        if not doc.make:
            missing_make += 1
        kinds[doc.narrative_kind] += 1
    warnings = []
    if documents and all(doc.demo for doc in documents):
        warnings.append("Every stored document is a DEMO fixture. These are not NHTSA records.")
    if not documents:
        warnings.append("No documents stored.")
    return {
        "record_count": len(documents),
        "missing_make": missing_make,
        "text_length_buckets": histogram(lengths),
        "common_dtcs": dtcs.most_common(10),
        "component_counts": components.most_common(10),
        "narrative_kinds": dict(kinds),
        "duplicate_checksums": _duplicate_checksums(documents),
        "warnings": warnings,
        "demo_count": sum(1 for doc in documents if doc.demo),
    }


def _duplicate_checksums(documents: list[SourceDocument]) -> int:
    seen = set()
    dupes = 0
    for doc in documents:
        if doc.checksum in seen:
            dupes += 1
        seen.add(doc.checksum)
    return dupes
