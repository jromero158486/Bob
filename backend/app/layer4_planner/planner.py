"""Free-text clinical task -> validated TaskPlan.

Primary: an LLM with JSON-schema output validated by Pydantic (LLMPlanDraft).
Fallback (no provider, provider error, or invalid plan): a transparent heuristic planner
over the concept vocabulary. The response always states which planner produced the plan.
"""
from __future__ import annotations

import json
import calendar
import re
from datetime import date

from pydantic import ValidationError

from backend.app.layer2_extraction.dates import find_dates
from backend.app.layer4_planner.contracts import (ALLOWED_OPERATIONS, LLMPlanDraft, PlannerInfo, PlanStep, Presentation,
                                                  StepFilters, TaskPlan, TemporalConstraint, validate_plan)
from backend.app.layer4_planner.vocabulary import CONCEPTS, GENERIC_DEFAULT, GLOSSARY, ROLE_DEFAULTS

_ROLE = re.compile(r"(?:I'?m|I am|you are|as)\s+(?:an?\s+|the\s+|her\s+|his\s+)?([A-Za-zÄÖÜäöü' -]{3,60}?)(?=[.,;:!?]| and | who | preparing| reviewing| planning| on | at |$)", re.I)
_ROLE_DE = re.compile(r"\bich bin\s+(?:ein(?:e)?\s+)?([A-Za-zÄÖÜäöü -]{3,40}?)(?=[.,;:!?]|$)", re.I)
_AS_OF = re.compile(r"\b(?:as of|stand|zum)\s+(.{6,25})", re.I)
_STOP = set("""i im i'm am a an the you are is was were be been she he her his him they their it its this that these those
of in on at to for from with by and or not no yes what which who when how does do did has have had should would could
can will please show list give me my our patient patients clinical task role about any all documented document documents
situation scheduled night duty arrives whether still open check checks there record records ich bin der die das und
ist sind mit für von zu im den dem des eine einer ein bitte welche welcher""".split())


def _role(request: str) -> str:
    m = _ROLE.search(request) or _ROLE_DE.search(request)
    return m.group(1).strip() if m else "clinician"


_MONTHS = {m: i for i, names in enumerate([
    ("januar", "jänner", "january", "jan"), ("februar", "february", "feb"), ("märz", "march", "mar"), ("april", "apr"),
    ("mai", "may"), ("juni", "june", "jun"), ("juli", "july", "jul"), ("august", "aug"),
    ("september", "sep", "sept"), ("oktober", "october", "okt", "oct"), ("november", "nov"), ("dezember", "december", "dez", "dec")],
    1) for m in names}
_REF = r"(?:as of|as at|on|in|during|by|until|zum|am|im|bis|stand|per)"
_ISO_REF = re.compile(rf"\b{_REF}\s+(\d{{4}}-\d{{2}}-\d{{2}})\b", re.I)
_MONTH_REF = re.compile(rf"\b{_REF}\s+({'|'.join(sorted(_MONTHS, key=len, reverse=True))})\.?\s+(\d{{4}})\b", re.I)


def _as_of(request: str) -> str | None:
    m = _AS_OF.search(request)
    if m:
        dates = [d for d in find_dates(m.group(1)) if d.valid]
        if dates:
            return dates[0].value
    m = _ISO_REF.search(request)
    if m:
        try:
            return date.fromisoformat(m.group(1)).isoformat()
        except ValueError:
            return None
    m = _MONTH_REF.search(request)
    if m:  # "im Januar 2021" -> state at the end of that month
        y, mo = int(m.group(2)), _MONTHS[m.group(1).casefold()]
        return date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()
    return None


def _search_terms(request: str) -> list[str]:
    words = re.findall(r"[A-Za-zÄÖÜäöüß-]{3,}", request)
    terms: list[str] = []
    low = request.casefold()
    for en, de in GLOSSARY.items():
        if en in low:
            terms += de
    terms += [w for w in words if w.casefold() not in _STOP and not w[0].isupper() or w.casefold() not in _STOP and
              any(ch in w for ch in "äöüß")]
    seen, out = set(), []
    for t in terms:
        if t.casefold() not in seen:
            seen.add(t.casefold())
            out.append(t)
    return out[:12]


def heuristic_plan(request: str, detail: str = "no LLM provider configured") -> TaskPlan:
    low = request.casefold()
    role = _role(request)
    matched = [c for c in CONCEPTS if any(re.search(t, low) for t in c["triggers"])]
    role_ids: list[str] = []
    for pattern, ids in ROLE_DEFAULTS:
        if re.search(pattern, role.casefold()) or re.search(pattern, low):
            role_ids = ids
            break
    by_id = {c["id"]: c for c in CONCEPTS}
    ordered = matched + [by_id[i] for i in role_ids if by_id[i] not in matched]
    if not ordered:
        ordered = [by_id[i] for i in GENERIC_DEFAULT]
    steps: list[PlanStep] = []
    seen_keys = set()
    terms = _search_terms(request)
    for c in ordered:
        for i, st in enumerate(c["steps"]):
            filters = dict(st.get("filters", {}))
            if st["operation"] == "search_text":
                filters["search_terms"] = terms
            key = (st["operation"], json.dumps(filters, sort_keys=True))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            steps.append(PlanStep(step_id=f"s{len(steps) + 1}", operation=st["operation"],
                                  title=st.get("title", c["title"]), concept=c["id"],
                                  filters=StepFilters(**filters), temporal=TemporalConstraint(**st.get("temporal", {})),
                                  required=st.get("required", True),
                                  rationale="matched in task text" if c in matched else f"default for role '{role}'"))
    if terms and not any(s.operation == "search_text" for s in steps):
        steps.append(PlanStep(step_id=f"s{len(steps) + 1}", operation="search_text", title="Other relevant passages",
                              concept="free_text", filters=StepFilters(search_terms=terms), required=False,
                              rationale="lexical search for task terms not covered by structured steps"))
    plan = TaskPlan(task_summary=request.strip()[:300], as_of=_as_of(request), steps=steps[:14],
                    presentation=Presentation(audience=role, emphasis=[c["id"] for c in matched],
                                              language="de" if re.search(r"\b(welche|ich|bin|sind|dokumentiert)\b", low) else "en"),
                    planner=PlannerInfo(name="heuristic-fallback", detail=detail))
    return validate_plan(plan)


SYSTEM = f"""You convert a clinician's free-text role and task into a read-only information-retrieval plan over ONE
patient's German clinical documents (already extracted into typed facts). Allowed operations: {', '.join(ALLOWED_OPERATIONS)}.
Use filters: code_prefixes (ATC for medications, e.g. B01 antithrombotics, A10 antidiabetics, C09 RAS blockers; ICD-10 for
diagnoses, e.g. C50 breast cancer, I65 carotid stenosis), observation_names (choose from: body_height, body_weight, bmi,
body_temperature, heart_rate, blood_pressure, lvef, hba1c, ki67, estrogen_receptor, progesterone_receptor, hormone_receptor,
her2, allred_score, tnm_classification, birads, stenosis_degree, lesion_size, mmse, tapse, creatinine, egfr),
procedure_names, statuses (planned, recommended, performed, historical), search_terms (German terms for lexical search).
temporal.mode: current (as of as_of), latest, series, all, change. Leave as_of null unless the user gives a reference date
(present tense means 'as of the latest document'). Mark required=true for information the task needs, so that absence is
shown as 'not documented'. Include what the role typically needs for this task even if not literally asked (e.g.
anaesthesia: antithrombotics, allergies, cardiac function). The role changes emphasis only, never data access.
Never include patient identifiers. Return 3-12 steps with short English titles."""


def llm_plan(request: str, provider) -> TaskPlan:
    resp = provider.complete_json(SYSTEM, request, LLMPlanDraft.model_json_schema(), "task_plan")
    draft = LLMPlanDraft.model_validate(resp.data)
    plan = TaskPlan(**draft.model_dump(), planner=PlannerInfo(name="llm", model=f"{resp.provider}:{resp.model}"))
    return validate_plan(plan)


def plan_task(request: str, provider=None) -> TaskPlan:
    if not request or not request.strip():
        raise ValueError("Empty task")
    if provider is None:
        return heuristic_plan(request)
    try:
        return llm_plan(request, provider)
    except (ValidationError, ValueError, KeyError, RuntimeError, OSError) as exc:
        plan = heuristic_plan(request, detail=f"LLM planner failed ({type(exc).__name__}); fallback used")
        plan.warnings.append("LLM plan rejected or unavailable; heuristic fallback plan shown")
        return plan
