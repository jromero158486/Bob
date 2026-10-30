"""Stable API contracts (also exported to frontend/src/api/types.ts). Versioned via API_VERSION."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.app.layer4_planner.contracts import TaskPlan

API_VERSION = "1.0"
ClaimStatus = Literal["supported", "contradicted", "not_addressed", "verification_incomplete"]
RetrievalMode = Literal["auto", "lexical", "dense", "hybrid", "hybrid_rerank"]
ClaimKind = Literal["fact", "computed", "documented_negative", "change", "passage", "not_documented"]


class Citation(BaseModel):
    document_id: str
    document_title: str
    document_date: str | None
    passage_id: str
    quote: str = Field(description="Exact source text of the cited span (readable form)")
    passage_text: str = Field(description="The full sentence/table row that contains the span")
    original_start: int
    original_end: int
    source_id: str = Field("", description="Exact document version (source) the offsets refer to")
    source_sha256: str = Field("", description="SHA-256 of the original source text of that version")
    verified: bool = Field(False, description="Citation integrity only: offsets, passage, quote, checksum, patient, "
                                              "current version. Says nothing about whether the claim is correct.")
    integrity_errors: list[str] = []


class Claim(BaseModel):
    claim_id: str
    text: str = Field(description="English rendering; numbers and names come from the source")
    original_text: str | None = Field(None, description="Original German wording")
    kind: ClaimKind
    status: ClaimStatus = "verification_incomplete"
    date: str | None = None
    codes: list[str] = []
    flags: list[str] = []
    fact_ids: list[str] = []
    citations: list[Citation] = []
    conflict_ids: list[str] = []
    review_status: str | None = None
    notes: list[str] = []
    citation_integrity: Literal["valid", "invalid", "none"] = "none"
    support_basis: Literal["source_values_matched", "verbatim_passage", "derived_from_verified_inputs",
                           "documented_negative", "absence_in_record", "none"] = "none"
    support_checks: list[str] = Field([], description="name:pass|fail for each semantic support check")


class Section(BaseModel):
    section_id: str
    step_id: str
    title: str
    concept: str
    operation: str
    outcome: Literal["answered", "not_documented", "documented_negative"]
    claims: list[Claim]


class MissingItem(BaseModel):
    step_id: str
    title: str
    message: str


class ConflictOut(BaseModel):
    conflict_id: str
    kind: str
    title: str
    explanation: str
    severity: str
    relevant_to_task: bool
    citations: list[Citation]
    review_status: str | None = None


class TimelineEvent(BaseModel):
    date: str
    kind: str
    label: str
    citations: list[Citation] = []


class VerificationSummary(BaseModel):
    supported: int = 0
    contradicted: int = 0
    not_addressed: int = 0
    citations_total: int = 0
    citations_valid: int = 0
    verification_incomplete: int = 0
    checks: list[str] = []


class Provenance(BaseModel):
    planner: str
    planner_model: str | None
    llm_configured: bool
    extraction_components: list[dict] = []
    database: str
    api_version: str = API_VERSION
    retrieval_mode: str | None = None
    retrieval_used: list[str] = []
    retrieval_warnings: list[str] = []


class TaskRequest(BaseModel):
    patient_id: str
    request: str = Field(min_length=3, max_length=2000)
    retrieval_mode: RetrievalMode | None = None


class TaskResponse(BaseModel):
    request_id: str
    patient_id: str
    request: str
    as_of: str | None
    plan: TaskPlan
    sections: list[Section]
    missing: list[MissingItem]
    conflicts: list[ConflictOut]
    timeline: list[TimelineEvent]
    verification: VerificationSummary
    provenance: Provenance
    timings_ms: dict[str, float]
    disclaimer: str = ("Research prototype on synthetic data. Facts are extracted from the source documents and "
                       "verified for provenance only; this is not a medical device and does not establish clinical truth.")


class PatientSummary(BaseModel):
    patient_id: str
    display_name: str | None
    document_count: int
    first_document_date: str | None
    last_document_date: str | None


class PassageOut(BaseModel):
    passage_id: str
    passage_type: str
    section: str | None
    section_title: str | None
    normalized_start: int
    normalized_end: int
    original_start: int
    original_end: int
    display_text: str


class DocumentOut(BaseModel):
    document_id: str
    title: str
    document_date: str | None
    document_type: str | None
    hospital: str | None
    source_sha256: str
    normalized_text: str | None = None
    passages: list[PassageOut] = []


class ReviewUpdate(BaseModel):
    item_key: str
    item_type: Literal["claim", "conflict"]
    summary: str = ""
    status: Literal["pending", "accepted", "rejected", "needs_more_info"]
    reviewer: str = Field(min_length=1, max_length=128)
    comment: str | None = None


VerifyJudge = Literal["nli", "groq", "none"]


class VerifyTextRequest(BaseModel):
    patient_id: str
    text: str = Field(min_length=3, max_length=5000, description="Free text (e.g. a draft summary) to check")
    as_of: str | None = Field(None, description="ISO date; evidence after it is ignored. Default: latest document")
    judge: VerifyJudge = Field("nli", description="nli (multilingual NLI), groq (LLM judge), none (deterministic)")
    atomizer: Literal["rules", "llm"] = "rules"
    retrieval_mode: RetrievalMode | None = None


class EvidenceOut(BaseModel):
    citation: Citation
    entailment: float | None = None
    contradiction: float | None = None
    checks: dict = {}


class AtomicClaimOut(BaseModel):
    text: str
    start: int | None = Field(None, description="Offset in the submitted text (rule atomizer only)")
    end: int | None = None
    verdict: Literal["supported", "contradicted", "not_addressed"]
    needs_review: bool
    review_reason: str
    clinically_verified: Literal[False] = Field(False, description="Always false: support by cited record text is not clinical verification")
    deterministic: dict = {}
    semantic: dict = {}
    evidence: list[EvidenceOut] = []


class VerifyTextResponse(BaseModel):
    patient_id: str
    as_of: str
    judge_requested: VerifyJudge
    judge_used: VerifyJudge
    judge_model: str | None = None
    atomizer: str
    retrieval_used: list[str] = []
    warnings: list[str] = []
    summary: dict[str, int] = {}
    claims: list[AtomicClaimOut] = []
    timings_ms: dict[str, float] = {}
    disclaimer: str = ("Research prototype on synthetic data. 'supported' means the claim is entailed by cited record "
                       "text and passes value/date/negation checks; it is not clinical verification.")
