"""Layer 2 contracts: evidence-linked clinical fact *candidates*.

A fact is a statement found in a source passage, not a verified clinical truth.
Every fact carries at least one EvidenceSpan whose raw text equals the exact
original source slice (Unicode codepoint offsets, version-locked by SHA-256).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FactType = Literal[
    "medication", "diagnosis", "observation", "procedure", "allergy",
    "recommendation", "encounter_event", "demographic",
]
DatePrecision = Literal["day", "month", "year"]
DateSource = Literal["explicit_in_passage", "section_heading", "relative_to_document", "document_date"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceSpan(_Frozen):
    patient_id: str
    document_id: str
    source_id: str
    source_sha256: str
    passage_id: str
    original_start: int
    original_end: int
    raw_text: str = Field(description="Exact original source slice [original_start:original_end]")
    display_text: str = Field(description="Readable projection (BR/entities resolved, whitespace collapsed)")
    role: Literal["mention", "value", "context_trigger", "date"] = "mention"


class Coding(_Frozen):
    system: str
    code: str
    display: str
    mapping_source: str = Field(description="Which lexicon/version produced this candidate code")
    level: Literal["specific", "category"] = "specific"


class ClinicalDate(_Frozen):
    value: str = Field(description="ISO 8601, possibly partial: YYYY, YYYY-MM or YYYY-MM-DD")
    precision: DatePrecision
    source: DateSource
    text: str | None = None


class ContextTrigger(_Frozen):
    category: Literal["NEGATED_EXISTENCE", "POSSIBLE_EXISTENCE", "HISTORICAL", "HYPOTHETICAL", "FAMILY"]
    text: str
    passage_offset: int


class Assertion(_Frozen):
    """ConText-style modifiers. 'negated' = documented absence (not missing data)."""
    negated: bool = False
    certainty: Literal["affirmed", "possible"] = "affirmed"
    temporality: Literal["current", "historical", "future"] = "current"
    experiencer: Literal["patient", "family"] = "patient"
    question: bool = False
    triggers: tuple[ContextTrigger, ...] = ()
    engine: str = "none"


class DoseSchedule(_Frozen):
    morning: float | None = None
    noon: float | None = None
    evening: float | None = None
    night: float | None = None
    text: str | None = None


class MedicationDetails(_Frozen):
    drug_text: str
    ingredient: str | None = None
    strength_value: float | None = None
    strength_unit: str | None = None
    form: str | None = None
    route: str | None = None
    schedule: DoseSchedule | None = None
    frequency_text: str | None = None
    dose_unit: str | None = None
    statement: Literal["medication_list", "started", "changed", "administered", "mentioned"] = "mentioned"
    unparsed: tuple[str, ...] = ()


class ObservationDetails(_Frozen):
    name: str
    name_text: str
    value_text: str
    value_num: float | None = None
    value_num2: float | None = Field(None, description="Second component, e.g. diastolic blood pressure")
    unit: str | None = None
    qualifier: str | None = Field(None, description="e.g. 24h mean, maximum, at admission")
    laterality: Literal["left", "right", "bilateral"] | None = None


class DiagnosisDetails(_Frozen):
    text: str
    laterality: Literal["left", "right", "bilateral"] | None = None
    listed_in_diagnosis_section: bool = False


class ProcedureDetails(_Frozen):
    text: str
    status: Literal["performed", "planned", "recommended", "historical", "mentioned"] = "mentioned"
    laterality: Literal["left", "right", "bilateral"] | None = None


class AllergyDetails(_Frozen):
    substance_text: str
    substance: str | None = None
    reactions: tuple[str, ...] = ()


class RecommendationDetails(_Frozen):
    text: str
    action: str | None = None
    due_text: str | None = None


class EncounterDetails(_Frozen):
    event: Literal["admission", "discharge", "visit", "sample_taken", "examination", "case_id"]
    date_text: str
    date_valid: bool


class DemographicDetails(_Frozen):
    attribute: Literal["birth_date", "age_years", "sex"]
    value: str


Details = (MedicationDetails | ObservationDetails | DiagnosisDetails | ProcedureDetails | AllergyDetails
           | RecommendationDetails | EncounterDetails | DemographicDetails)


class ExtractorInfo(_Frozen):
    name: str
    version: str


class ClinicalFact(_Frozen):
    fact_id: str
    fact_type: FactType
    patient_id: str
    document_id: str
    source_id: str
    label: str
    details: Details
    codings: tuple[Coding, ...] = ()
    assertion: Assertion = Assertion()
    event_date: ClinicalDate | None = Field(None, description="When the clinical event happened, if documented")
    document_date: str | None = Field(None, description="Date of the source document (not the event)")
    section: str | None = None
    evidence: tuple[EvidenceSpan, ...]
    extractor: ExtractorInfo
    supporting_extractors: tuple[ExtractorInfo, ...] = ()
    review_status: Literal["unreviewed", "needs_review"] = "unreviewed"
    notes: tuple[str, ...] = ()


def make_fact_id(*parts: object) -> str:
    return "fact:" + hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:20]


class ComponentRun(_Frozen):
    name: str
    version: str
    status: Literal["ran", "unavailable", "disabled", "failed"]
    detail: str = ""


class ExtractionRun(BaseModel):
    run_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    patient_ids: list[str] = []
    document_ids: list[str] = []
    components: list[ComponentRun] = []
    resource_checksums: dict[str, str] = {}
    fact_counts: dict[str, int] = {}
    warnings: list[str] = []


class ExtractionResult(BaseModel):
    run: ExtractionRun
    facts: list[ClinicalFact]
