// AUTO-GENERATED from docs/openapi.json by backend/app/tools/gen_ts_types.py. Do not edit.

export type Citation = {
  document_id: string;
  document_title: string;
  document_date: string | null;
  passage_id: string;
  quote: string;
  passage_text: string;
  original_start: number;
  original_end: number;
  source_id?: string;
  source_sha256?: string;
  verified?: boolean;
  integrity_errors?: string[];
};

export type Claim = {
  claim_id: string;
  text: string;
  original_text?: string | null;
  kind: "fact" | "computed" | "documented_negative" | "change" | "passage" | "not_documented";
  status?: "supported" | "contradicted" | "not_addressed" | "verification_incomplete";
  date?: string | null;
  codes?: string[];
  flags?: string[];
  fact_ids?: string[];
  citations?: Citation[];
  conflict_ids?: string[];
  review_status?: string | null;
  notes?: string[];
  citation_integrity?: "valid" | "invalid" | "none";
  support_basis?: "source_values_matched" | "verbatim_passage" | "derived_from_verified_inputs" | "documented_negative" | "absence_in_record" | "none";
  support_checks?: string[];
};

export type ConflictOut = {
  conflict_id: string;
  kind: string;
  title: string;
  explanation: string;
  severity: string;
  relevant_to_task: boolean;
  citations: Citation[];
  review_status?: string | null;
};

export type DocumentOut = {
  document_id: string;
  title: string;
  document_date: string | null;
  document_type: string | null;
  hospital: string | null;
  source_sha256: string;
  normalized_text?: string | null;
  passages?: PassageOut[];
};

export type HTTPValidationError = {
  detail?: ValidationError[];
};

export type MissingItem = {
  step_id: string;
  title: string;
  message: string;
};

export type PassageOut = {
  passage_id: string;
  passage_type: string;
  section: string | null;
  section_title: string | null;
  normalized_start: number;
  normalized_end: number;
  original_start: number;
  original_end: number;
  display_text: string;
};

export type PatientSummary = {
  patient_id: string;
  display_name: string | null;
  document_count: number;
  first_document_date: string | null;
  last_document_date: string | null;
};

export type PlanStep = {
  step_id: string;
  operation: "list_medications" | "compare_medication_lists" | "list_diagnoses" | "list_allergies" | "get_observations" | "list_procedures" | "list_recommendations" | "check_followups" | "list_encounters" | "demographics" | "search_text";
  title: string;
  concept: string;
  filters?: StepFilters;
  temporal?: TemporalConstraint;
  required?: boolean;
  rationale?: string | null;
};

export type PlannerInfo = {
  name: "llm" | "heuristic-fallback";
  model?: string | null;
  detail?: string;
};

export type Presentation = {
  audience: string;
  emphasis?: string[];
  language?: "en" | "de";
};

export type Provenance = {
  planner: string;
  planner_model: string | null;
  llm_configured: boolean;
  extraction_components?: Record<string, unknown>[];
  database: string;
  api_version?: string;
};

export type ReviewUpdate = {
  item_key: string;
  item_type: "claim" | "conflict";
  summary?: string;
  status: "pending" | "accepted" | "rejected" | "needs_more_info";
  reviewer: string;
  comment?: string | null;
};

export type Section = {
  section_id: string;
  step_id: string;
  title: string;
  concept: string;
  operation: string;
  outcome: "answered" | "not_documented" | "documented_negative";
  claims: Claim[];
};

export type StepFilters = {
  code_prefixes?: string[];
  observation_names?: string[];
  procedure_names?: string[];
  search_terms?: string[];
  require_terms?: string[];
  statuses?: string[];
};

export type TaskPlan = {
  task_summary: string;
  as_of?: string | null;
  steps: PlanStep[];
  presentation: Presentation;
  planner: PlannerInfo;
  warnings?: string[];
};

export type TaskRequest = {
  patient_id: string;
  request: string;
};

export type TaskResponse = {
  request_id: string;
  patient_id: string;
  request: string;
  as_of: string | null;
  plan: TaskPlan;
  sections: Section[];
  missing: MissingItem[];
  conflicts: ConflictOut[];
  timeline: TimelineEvent[];
  verification: VerificationSummary;
  provenance: Provenance;
  timings_ms: Record<string, number>;
  disclaimer?: string;
};

export type TemporalConstraint = {
  mode?: "current" | "latest" | "series" | "all" | "change";
  as_of?: string | null;
  date_from?: string | null;
  date_to?: string | null;
};

export type TimelineEvent = {
  date: string;
  kind: string;
  label: string;
  citations?: Citation[];
};

export type ValidationError = {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
};

export type VerificationSummary = {
  supported?: number;
  contradicted?: number;
  not_addressed?: number;
  citations_total?: number;
  citations_valid?: number;
  verification_incomplete?: number;
  checks?: string[];
};
