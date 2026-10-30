"""Layer 4 contracts: a free-text clinical task becomes a typed, read-only TaskPlan.

The professional role only influences presentation (emphasis, ordering, wording);
it never grants or restricts data access. Plans cannot name a patient: the patient
is bound by the API request, so a plan cannot reach another patient's record.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Operation = Literal[
    "list_medications",          # current medication list (as of) + narrative statements
    "compare_medication_lists",  # changes between consecutive medication lists (admissions)
    "list_diagnoses",
    "list_allergies",
    "get_observations",          # named measurements: latest value or series
    "list_procedures",
    "list_recommendations",
    "check_followups",           # were recommended follow-up procedures documented later?
    "list_encounters",
    "demographics",
    "search_text",               # lexical retrieval over original passages
]
ALLOWED_OPERATIONS: tuple[str, ...] = Operation.__args__  # type: ignore[attr-defined]


class StepFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code_prefixes: list[str] = Field(default_factory=list, description="ATC or ICD-10 code prefixes, e.g. B01, A10, C50")
    observation_names: list[str] = Field(default_factory=list, description="Canonical observation names")
    procedure_names: list[str] = Field(default_factory=list, description="Procedure display names (English)")
    search_terms: list[str] = Field(default_factory=list, description="German/English terms for lexical search")
    require_terms: list[str] = Field(default_factory=list,
                                     description="Lexical hits must contain one of these substrings (case-insensitive); "
                                                 "otherwise the step reports 'not documented'")
    statuses: list[str] = Field(default_factory=list, description="e.g. planned, recommended, performed")


class TemporalConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["current", "latest", "series", "all", "change"] = "all"
    as_of: str | None = Field(None, description="ISO date; null = date of the latest document")
    date_from: str | None = None
    date_to: str | None = None


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    operation: Operation
    title: str = Field(description="Short heading shown to the user")
    concept: str = Field(description="What clinical information this step looks for")
    filters: StepFilters = Field(default_factory=StepFilters)
    temporal: TemporalConstraint = Field(default_factory=TemporalConstraint)
    required: bool = Field(True, description="If nothing is found, show 'not documented'")
    rationale: str | None = None


class Presentation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audience: str = Field(description="The user's stated role, free text")
    emphasis: list[str] = Field(default_factory=list)
    language: Literal["en", "de"] = "en"


class PlannerInfo(BaseModel):
    name: Literal["llm", "heuristic-fallback"]
    model: str | None = None
    detail: str = ""


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_summary: str
    as_of: str | None = None
    steps: list[PlanStep] = Field(min_length=1, max_length=14)
    presentation: Presentation
    planner: PlannerInfo
    warnings: list[str] = Field(default_factory=list)


class LLMPlanDraft(BaseModel):
    """Schema the LLM must fill (planner metadata is added by the system, not the model)."""
    model_config = ConfigDict(extra="forbid")
    task_summary: str
    as_of: str | None = None
    steps: list[PlanStep] = Field(min_length=1, max_length=14)
    presentation: Presentation


def validate_plan(plan: TaskPlan) -> TaskPlan:
    ids = [s.step_id for s in plan.steps]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate step ids")
    for s in plan.steps:
        if s.operation not in ALLOWED_OPERATIONS:
            raise ValueError(f"Operation not allowed: {s.operation}")
    return plan
