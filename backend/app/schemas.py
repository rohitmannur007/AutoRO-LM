"""Versioned API and domain schemas (schema_version 1.0.0)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app import SCHEMA_VERSION

SplitName = Literal["train", "validation", "test", "reference"]
ReviewStatus = Literal["pending", "approved", "rejected"]
JobStatus = Literal["queued", "running", "completed", "failed"]
SupportStatus = Literal["supported", "partial", "unsupported", "unknown"]


class VehicleInfo(BaseModel):
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    vin: str | None = None

    @field_validator("vin")
    @classmethod
    def vin_shape(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        cleaned = value.strip().upper()
        if not cleaned.isalnum() or not 11 <= len(cleaned) <= 17:
            raise ValueError("VIN must be 11–17 alphanumeric characters when supplied")
        return cleaned

    @field_validator("model_year")
    @classmethod
    def year_range(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1980 or value > 2035:
            raise ValueError("model_year must be between 1980 and 2035")
        return value


class EvidenceSpan(BaseModel):
    field_name: str
    quoted_text: str
    source_text_id: str | None = None
    source_document_id: str | None = None
    start: int | None = None
    end: int | None = None
    evidence_type: str = "literal"
    support_status: SupportStatus = "supported"


class ProviderMetadata(BaseModel):
    provider: str
    model: str | None = None
    is_llm: bool = False
    demo: bool = False
    model_revision: str | None = None
    prompt_version: str | None = None
    caveats: list[str] = Field(default_factory=list)


class ExtractionTarget(BaseModel):
    """Human or fixture annotation. No provider metadata and no confidence."""

    symptom: str | None = None
    dtc_codes: list[str] = Field(default_factory=list)
    component: str | None = None
    suspected_component: str | None = None
    repair_action: str | None = None
    complaint: str | None = None
    cause: str | None = None
    correction: str | None = None
    vehicle: VehicleInfo = Field(default_factory=VehicleInfo)


class ExtractionResult(BaseModel):
    extraction_id: str
    schema_version: str = SCHEMA_VERSION
    symptom: str | None = None
    dtc_codes: list[str] = Field(default_factory=list)
    component: str | None = None
    suspected_component: str | None = None
    repair_action: str | None = None
    complaint: str | None = None
    cause: str | None = None
    correction: str | None = None
    unknown_fields: list[str] = Field(default_factory=list)
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    vehicle: VehicleInfo = Field(default_factory=VehicleInfo)
    provider: ProviderMetadata
    created_at: datetime
    demo: bool = False
    schema_valid: bool = True
    validation_errors: list[str] = Field(default_factory=list)
    # Confidence is omitted unless a provider truly returns a calibrated score.
    field_support: dict[str, str] = Field(default_factory=dict)


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    vehicle: VehicleInfo | None = None
    provider: str | None = None


class SourceDocument(BaseModel):
    document_id: str
    source_type: str
    source_url: str | None = None
    source_name: str
    retrieved_at: datetime | None = None
    published_at: str | None = None
    license_notes: str = ""
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    component: str | None = None
    dtc_codes: list[str] = Field(default_factory=list)
    text: str
    raw_text: str
    checksum: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    ingestion_status: str = "loaded"
    demo: bool = False
    schema_version: str = SCHEMA_VERSION
    source_group: str = ""
    split: SplitName = "train"
    allow_synthetic_seed: bool = False
    narrative_kind: str = "demo_note"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding_status: str = "not_applicable"


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    start_offset: int
    end_offset: int
    score: float
    rank: int
    source_url: str | None = None
    source_name: str = ""
    source_type: str = ""
    demo: bool = False
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    highlights: list[dict[str, int]] = Field(default_factory=list)
    retrieval: str = "lexical"
    score_detail: dict[str, float] = Field(default_factory=dict)


class Citation(BaseModel):
    citation_id: str
    chunk_id: str
    document_id: str
    quote: str
    source_url: str | None = None
    support_status: SupportStatus = "supported"


class QAFilters(BaseModel):
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    dtc: str | None = None
    component: str | None = None
    document_type: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    filters: QAFilters | None = None
    top_k: int = Field(default=5, ge=1, le=10)
    provider: str | None = None
    retrieval_mode: Literal["lexical", "vector", "hybrid"] | None = None


class QAResponse(BaseModel):
    request_id: str
    schema_version: str = SCHEMA_VERSION
    question: str
    filters: QAFilters = Field(default_factory=QAFilters)
    answer: str
    abstained: bool
    abstain_reason: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    provider: ProviderMetadata
    latency_ms: float
    demo: bool = False
    safety_notice: str
    evaluation: dict[str, Any] | None = None
    conflicts: list[str] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)


class JobRecord(BaseModel):
    job_id: str
    job_type: str
    action: str
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)


class IngestionJobRequest(BaseModel):
    source: Literal["demo_fixtures", "nhtsa_complaints", "nhtsa_recalls", "nhtsa_mfr_comms"]
    make: str | None = None
    model: str | None = None
    model_year: int | None = None
    max_records: int = Field(default=25, ge=1, le=200)
    url: str | None = None


class SyntheticJobRequest(BaseModel):
    seed_document_ids: list[str] = Field(default_factory=list)
    variations: list[Literal["abbreviation", "capitalization", "typos", "terse", "ccc"]] = Field(
        default_factory=lambda: ["abbreviation", "terse", "ccc"]
    )
    count: int = Field(default=3, ge=1, le=50)
    teacher: Literal["deterministic_demo", "ollama"] = "deterministic_demo"


class ReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    reason: str = Field(default="", max_length=500)


class SyntheticExample(BaseModel):
    example_id: str
    schema_version: str = SCHEMA_VERSION
    input_text: str
    expected_json: ExtractionTarget
    seed_document_ids: list[str]
    source_group: str
    generation_provider: str
    generation_model: str | None = None
    generation_prompt_version: str
    is_llm: bool = False
    demo: bool = False
    created_at: datetime
    validation_checks: list[dict[str, Any]] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = "pending"
    review_reason: str = ""
    split: SplitName = "train"
    provenance_label: Literal["synthetic"] = "synthetic"
    variation: str = ""
    judge_signal: dict[str, Any] | None = None


class GoldExample(BaseModel):
    example_id: str
    schema_version: str = SCHEMA_VERSION
    source_document_ids: list[str] = Field(default_factory=list)
    source_group: str
    input_text: str
    target: ExtractionTarget
    component_category: str | None = None
    annotation_guideline_version: str = "1.0.0"
    reviewer_notes: str = ""
    reviewer_id: str = ""
    split: SplitName
    created_at: datetime
    demo: bool = True


class ExperimentRun(BaseModel):
    run_id: str
    schema_version: str = SCHEMA_VERSION
    task: str
    model_provider: str
    model_revision: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    dataset_version: str = "demo-1.0.0"
    synthetic_share: float | None = None
    training_settings: dict[str, Any] = Field(default_factory=dict)
    seed: int = 42
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: list[str] = Field(default_factory=list)
    runtime_seconds: float | None = None
    hardware: dict[str, Any] = Field(default_factory=dict)
    commit_hash: str | None = None
    status: str
    logs: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    parent_experiment_id: str | None = None
    caveats: list[str] = Field(default_factory=list)


class EvaluationRequest(BaseModel):
    task: Literal[
        "extraction_rules",
        "extraction_provider",
        "component_classifier",
        "retrieval_comparison",
        "qa_rag",
        "synthetic_share",
        "synthetic_share_llm",
        "filtered_vs_unfiltered",
    ]


class TrainingJobRequest(BaseModel):
    dry_run: bool = True
    mixture_share: float = Field(default=0.0, ge=0.0, le=1.0)
    iters: int | None = Field(default=None, ge=1, le=200)
    model: str | None = None
    confirm: str = ""


class SplitAssignRequest(BaseModel):
    seed: int = 42


class EligibilityRequest(BaseModel):
    confirm: str
    document_ids: list[str] = Field(default_factory=list)


class GoldWriteRequest(BaseModel):
    example_id: str = Field(min_length=3, max_length=80)
    source_document_ids: list[str] = Field(default_factory=list)
    source_group: str = Field(min_length=1, max_length=120)
    input_text: str = Field(min_length=1, max_length=8000)
    target: ExtractionTarget
    component_category: str | None = None
    annotation_guideline_version: str = "1.0.0"
    reviewer_notes: str = ""
    reviewer_id: str = ""
    split: SplitName
    demo: bool = False


class VehicleQuery(BaseModel):
    make: str
    model: str
    model_year: int


class CollectionRequest(BaseModel):
    vehicles: list[VehicleQuery] = Field(min_length=1, max_length=8)
    max_records_each: int = Field(default=25, ge=1, le=100)
    include_recalls: bool = False
    assign_splits: bool = True


class ProviderHealth(BaseModel):
    name: str
    role: str
    available: bool
    is_llm: bool
    demo: bool
    model: str | None = None
    detail: str = ""


class DatabaseStatus(BaseModel):
    configured_adapter: str
    active_adapter: str
    connected: bool
    fallback: bool = False
    detail: str = ""
    path: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    schema_version: str
    demo_provider: bool
    database: DatabaseStatus
    providers: list[ProviderHealth]
    retrieval: dict[str, Any]
    secrets_exposed: bool = False


class StatusResponse(BaseModel):
    demo_data: bool
    demo_provider: bool
    database: DatabaseStatus
    counts: dict[str, Any]
    index: dict[str, Any]
    providers: list[ProviderHealth]
    recent_jobs: list[JobRecord]
    evaluation_count: int
    safety_notice: str


class SettingsView(BaseModel):
    environment: str
    provider: str
    teacher_provider: str
    retrieval_mode: str
    data_dir: str
    database: DatabaseStatus
    ollama_base_url: str
    ollama_model: str
    ollama_configured_model_only: bool = True
    hosted_provider_configured: bool
    hosted_key_present: bool
    max_extract_chars: int
    max_synthetic_count: int
    jobs_inline: bool
    privacy_note: str
    mlx_model: str = ""
    mlx_adapter_dir: str = ""
    mlx_adapter_trained: bool = False
    mlx_detail: str = ""


class SettingsUpdate(BaseModel):
    retrieval_mode: Literal["lexical", "vector", "hybrid"] | None = None
    provider: Literal["demo", "ollama", "openai_compatible", "mlx"] | None = None
    teacher_provider: Literal["deterministic_demo", "ollama", "none"] | None = None


class ResetRequest(BaseModel):
    confirm: str


SAFETY_NOTICE = (
    "Informational research output only. Consult the manufacturer's service "
    "information and a qualified technician before any repair, especially on "
    "brakes, steering, airbags, fuel, and high-voltage systems. A diagnostic "
    "trouble code alone is not proof that a component has failed."
)
