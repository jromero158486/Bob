"""Stable API contracts (also exported to frontend/src/api/types.ts). Versioned via API_VERSION."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.app.layer4_planner.contracts import TaskPlan

API_VERSION = "1.0"
ClaimStatus = Literal["supported", "contradicted", "not_addressed", "verification_incomplete"]
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
    verified: bool = False


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
    verification_incomplete: int = 0
    checks: list[str] = []


class Provenance(BaseModel):
    planner: str
    planner_model: str | None
    llm_configured: bool
    extraction_components: list[dict] = []
    database: str
    api_version: str = API_VERSION


class TaskRequest(BaseModel):
    patient_id: str
    request: str = Field(min_length=3, max_length=2000)


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
