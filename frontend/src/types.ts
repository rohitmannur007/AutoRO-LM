export type DatabaseStatus = {
  configured_adapter: string;
  active_adapter: string;
  connected: boolean;
  fallback: boolean;
  detail: string;
  path?: string | null;
};

export type ProviderHealth = {
  name: string;
  role: string;
  available: boolean;
  is_llm: boolean;
  demo: boolean;
  model?: string | null;
  detail: string;
};

export type Health = {
  status: "ok" | "degraded";
  version: string;
  schema_version: string;
  demo_provider: boolean;
  database: DatabaseStatus;
  providers: ProviderHealth[];
  retrieval: Record<string, unknown>;
  secrets_exposed: boolean;
};

export type Job = {
  job_id: string;
  job_type: string;
  action: string;
  status: "queued" | "running" | "completed" | "failed";
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  counts: Record<string, number>;
  errors: string[];
  metadata: Record<string, unknown>;
  logs: string[];
};

export type Status = {
  demo_data: boolean;
  demo_provider: boolean;
  database: DatabaseStatus;
  counts: Record<string, number>;
  index: Record<string, unknown>;
  providers: ProviderHealth[];
  recent_jobs: Job[];
  evaluation_count: number;
  safety_notice: string;
};

export type Evidence = {
  field_name: string;
  quoted_text: string;
  start?: number | null;
  end?: number | null;
  evidence_type: string;
  support_status: string;
};

export type Extraction = {
  extraction_id: string;
  schema_version: string;
  symptom?: string | null;
  dtc_codes: string[];
  component?: string | null;
  suspected_component?: string | null;
  repair_action?: string | null;
  complaint?: string | null;
  cause?: string | null;
  correction?: string | null;
  unknown_fields: string[];
  evidence: Evidence[];
  vehicle: { make?: string | null; model?: string | null; model_year?: number | null; vin?: string | null };
  provider: { provider: string; model?: string | null; is_llm: boolean; demo: boolean; caveats: string[] };
  created_at: string;
  demo: boolean;
  schema_valid: boolean;
  validation_errors: string[];
  field_support: Record<string, string>;
};

export type Citation = {
  citation_id: string;
  chunk_id: string;
  document_id: string;
  quote: string;
  source_url?: string | null;
  support_status: string;
};

export type Retrieved = {
  chunk_id: string;
  document_id: string;
  text: string;
  score: number;
  rank: number;
  source_url?: string | null;
  source_name: string;
  source_type: string;
  demo: boolean;
  make?: string | null;
  model?: string | null;
  model_year?: number | null;
  highlights: { start: number; end: number }[];
  retrieval: string;
  score_detail: Record<string, number>;
};

export type QAResponse = {
  request_id: string;
  question: string;
  answer: string;
  abstained: boolean;
  abstain_reason?: string | null;
  citations: Citation[];
  retrieved_chunk_ids: string[];
  retrieved: Retrieved[];
  provider: { provider: string; is_llm: boolean; demo: boolean; model?: string | null; caveats: string[] };
  latency_ms: number;
  demo: boolean;
  safety_notice: string;
  conflicts: string[];
  claims?: { claim: string; support_status: string; method: string; entailment_judged: boolean }[];
};

export type SourceDocument = {
  document_id: string;
  source_type: string;
  source_url?: string | null;
  source_name: string;
  retrieved_at?: string | null;
  make?: string | null;
  model?: string | null;
  model_year?: number | null;
  text: string;
  checksum: string;
  provenance: Record<string, unknown>;
  demo: boolean;
  split: string;
  narrative_kind: string;
  allow_synthetic_seed: boolean;
  ingestion_status: string;
};

export type SyntheticExample = {
  example_id: string;
  input_text: string;
  expected_json: Record<string, unknown>;
  seed_document_ids: string[];
  generation_provider: string;
  generation_model?: string | null;
  generation_prompt_version: string;
  is_llm: boolean;
  demo: boolean;
  created_at: string;
  validation_checks: { name: string; passed?: boolean; jaccard?: number }[];
  quality_flags: string[];
  review_status: "pending" | "approved" | "rejected";
  review_reason: string;
  provenance_label: string;
  variation: string;
  split: string;
};

export type ExperimentRun = {
  run_id: string;
  task: string;
  model_provider: string;
  model_revision?: string | null;
  dataset_version: string;
  synthetic_share?: number | null;
  metrics: Record<string, unknown>;
  runtime_seconds?: number | null;
  hardware: Record<string, unknown>;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  caveats: string[];
  seed: number;
};

export type SettingsView = {
  environment: string;
  provider: string;
  teacher_provider: string;
  retrieval_mode: string;
  data_dir: string;
  database: DatabaseStatus;
  ollama_base_url: string;
  ollama_model: string;
  hosted_provider_configured: boolean;
  hosted_key_present: boolean;
  max_extract_chars: number;
  max_synthetic_count: number;
  jobs_inline: boolean;
  privacy_note: string;
  mlx_model: string;
  mlx_adapter_dir: string;
  mlx_adapter_trained: boolean;
  mlx_detail: string;
};

export type Profile = {
  record_count: number;
  missing_make: number;
  text_length_buckets: Record<string, number>;
  common_dtcs: [string, number][];
  component_counts: [string, number][];
  narrative_kinds: Record<string, number>;
  duplicate_checksums: number;
  warnings: string[];
  demo_count: number;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
