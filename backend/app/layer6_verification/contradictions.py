"""Deterministic documentation-conflict detection over one patient's facts.

A conflict is reported only when the statements cannot all be true *for the same event or
document*; values from different dates/encounters are treated as change over time, and small
across-visit measurement differences are not flagged. Every conflict links all its facts.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date

from pydantic import BaseModel

from backend.app.layer2_extraction.contracts import ClinicalFact


class Conflict(BaseModel):
    conflict_id: str
    kind: str
    title: str
    explanation: str
    severity: str  # high | medium | low
    fact_ids: list[str]
    concepts: list[str] = []
    disputed_fact_ids: list[str] | None = None  # facts whose truth is in question (default: all)


def _cid(kind: str, ids) -> str:
    return "conflict:" + hashlib.sha256((kind + "|" + "|".join(sorted(ids))).encode()).hexdigest()[:16]


def _ok(f: ClinicalFact) -> bool:
    a = f.assertion
    return not a.question and a.experiencer == "patient" and a.certainty == "affirmed"


def _days(a: str | None, b: str | None) -> int | None:
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
    except (TypeError, ValueError):
        return None


# ICD-10 categories that denote one clinical concept for presence/absence checks ("Kein Diabetes mellitus" vs E11).
_FAMILIES = {"E10": "diabetes", "E11": "diabetes", "E12": "diabetes", "E13": "diabetes", "E14": "diabetes"}


def _family(code: str) -> str:
    return _FAMILIES.get(code[:3], code)


def detect_conflicts(facts: list[ClinicalFact]) -> list[Conflict]:
    out: list[Conflict] = []
    by_doc: dict[str, list[ClinicalFact]] = defaultdict(list)
    for f in facts:
        by_doc[f.document_id].append(f)

    for doc_id, fs in by_doc.items():
        obs = [f for f in fs if f.fact_type == "observation" and _ok(f) and not f.assertion.negated]
        get = lambda n: next((f for f in obs if f.details.name == n and f.details.value_num), None)  # noqa: E731
        bmi, w, h = get("bmi"), get("body_weight"), get("body_height")
        if bmi and w and h and h.details.value_num > 50:
            calc = w.details.value_num / (h.details.value_num / 100) ** 2
            if abs(calc - bmi.details.value_num) > 1.0:
                out.append(Conflict(conflict_id=_cid("bmi", [bmi.fact_id, w.fact_id, h.fact_id]), kind="bmi_mismatch",
                                    title=f"BMI {bmi.details.value_text} does not match height and weight",
                                    explanation=(f"{w.details.value_num:g} kg and {h.details.value_num:g} cm give a BMI of "
                                                 f"{calc:.1f} (calculated), but the same document states BMI "
                                                 f"{bmi.details.value_text}."),
                                    severity="medium", fact_ids=[bmi.fact_id, w.fact_id, h.fact_id],
                                    disputed_fact_ids=[bmi.fact_id],
                                    concepts=["bmi", "body_weight", "body_height"]))
        # Same document, same measurement and qualifier, different value (e.g. BP at admission).
        groups: dict[tuple, list[ClinicalFact]] = defaultdict(list)
        for f in obs:
            if f.details.qualifier in ("at admission",):
                groups[(f.details.name, f.details.qualifier)].append(f)
        for (name, qual), g in groups.items():
            vals = {(f.details.value_num, f.details.value_num2) for f in g}
            if len(vals) > 1:
                ids = [f.fact_id for f in g]
                out.append(Conflict(conflict_id=_cid("value", ids), kind="value_conflict",
                                    title=f"Different {name.replace('_', ' ')} values {qual} in one document",
                                    explanation="The same document gives " + " vs ".join(sorted({f.details.value_text for f in g}))
                                                + f" for {name.replace('_', ' ')} {qual}.",
                                    severity="low", fact_ids=ids, concepts=[name]))
        # Encounter dates: two different admission/discharge dates for the same stay in one document.
        for ev in ("admission", "discharge"):
            g = [f for f in fs if f.fact_type == "encounter_event" and f.details.event == ev
                 and f.assertion.temporality != "future"]
            values = {(f.event_date.value if f.event_date else f"invalid:{f.details.date_text}") for f in g}
            if len(values) > 1:
                ids = [f.fact_id for f in g]
                invalid = [f.details.date_text for f in g if not f.details.date_valid]
                out.append(Conflict(conflict_id=_cid(ev, ids), kind="date_conflict",
                                    title=f"Inconsistent {ev} date in one document",
                                    explanation=f"The document gives {ev} as " + " and ".join(sorted(f.details.date_text for f in g))
                                                + (f"; '{invalid[0]}' is not a valid date." if invalid else "."),
                                    severity="medium", fact_ids=ids, concepts=["encounter"]))

    # Laterality conflicts for the same concept within one document.
    for doc_id, fs in by_doc.items():
        lat: dict[str, list[ClinicalFact]] = defaultdict(list)
        for f in fs:
            if not _ok(f) or f.assertion.negated:
                continue
            d = f.details
            side = getattr(d, "laterality", None)
            if side not in ("left", "right"):
                continue
            key = d.name if f.fact_type == "observation" else (f.codings[0].code if f.codings else None)
            if key:
                lat[key].append(f)
        for key, g in lat.items():
            sides = {f.details.laterality for f in g}
            if sides == {"left", "right"}:
                ids = [f.fact_id for f in g]
                out.append(Conflict(conflict_id=_cid("lat", ids), kind="laterality_conflict",
                                    title=f"Left and right both documented for the same finding ({g[0].label[:40]})",
                                    explanation="Within one document the same finding is described on the left in some "
                                                "passages and on the right in others.",
                                    severity="high", fact_ids=ids, concepts=[key]))

    # Same finding affirmed and negated within 30 days (different documents or passages).
    by_code: dict[str, list[ClinicalFact]] = defaultdict(list)
    for f in facts:
        if f.fact_type == "diagnosis" and f.codings and not f.assertion.question and f.assertion.experiencer == "patient" \
                and f.assertion.temporality == "current":
            by_code[_family(f.codings[0].code)].append(f)
    for code, g in by_code.items():
        pos = [f for f in g if not f.assertion.negated and f.assertion.certainty == "affirmed"]
        neg = [f for f in g if f.assertion.negated]
        for p in pos:
            for n in neg:
                d = _days(p.document_date, n.document_date)
                if d is not None and d > 30 and (p.document_date or "") < (n.document_date or ""):
                    ids = [p.fact_id, n.fact_id]  # affirmed earlier, explicitly denied later
                    out.append(Conflict(conflict_id=_cid("negl", ids), kind="presence_conflict",
                                        title=f"{p.codings[0].display}: present on {p.document_date}, documented absent "
                                              f"on {n.document_date}",
                                        explanation="A diagnosis documented earlier is explicitly negated in a later "
                                                    "document. This may be resolution or a documentation error; check.",
                                        severity="low", fact_ids=ids, concepts=[code]))
                if d is not None and d <= 30 and p.evidence[0].passage_id != n.evidence[0].passage_id:
                    ids = [p.fact_id, n.fact_id]
                    out.append(Conflict(conflict_id=_cid("neg", ids), kind="presence_conflict",
                                        title=f"{p.codings[0].display}: documented as present and as absent",
                                        explanation=f"Documented as present ({p.document_date}) and explicitly absent "
                                                    f"({n.document_date}) within {d} days.",
                                        severity="medium", fact_ids=ids, concepts=[code]))

    # Stated age vs birth date at the document date.
    dobs = [f for f in facts if f.fact_type == "demographic" and f.details.attribute == "birth_date"]
    for f in facts:
        if f.fact_type == "demographic" and f.details.attribute == "age_years" and dobs and f.document_date:
            dob = date.fromisoformat(dobs[0].details.value)
            ref = date.fromisoformat(f.document_date)
            age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
            if abs(age - int(f.details.value)) >= 1:
                ids = [f.fact_id, dobs[0].fact_id]
                out.append(Conflict(conflict_id=_cid("age", ids), kind="age_conflict", title="Stated age does not match birth date",
                                    explanation=f"Stated age {f.details.value}, but birth date gives {age} on {f.document_date}.",
                                    severity="low", fact_ids=ids, concepts=["demographics"]))

    # One case number used for stays far apart in time.
    cases: dict[str, list[ClinicalFact]] = defaultdict(list)
    for f in facts:
        if f.fact_type == "encounter_event" and f.details.event == "case_id":
            cases[f.details.date_text].append(f)
    for case, g in cases.items():
        dated = sorted((f for f in g if f.document_date), key=lambda f: f.document_date)
        if len(dated) > 1 and (_days(dated[0].document_date, dated[-1].document_date) or 0) > 90:
            outliers = [f for f in dated if (_days(dated[0].document_date, f.document_date) or 0) > 90]
            ids = [dated[0].fact_id] + [f.fact_id for f in outliers]
            out.append(Conflict(conflict_id=_cid("case", ids), kind="identifier_conflict",
                                title=f"Case number {case} used for different hospital stays",
                                explanation=f"Case number {case} appears in documents from {dated[0].document_date} and "
                                            f"{outliers[0].document_date}, more than 90 days apart.",
                                severity="low", fact_ids=ids, concepts=["encounter"]))
    return out
