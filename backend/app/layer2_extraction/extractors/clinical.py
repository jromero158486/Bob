"""Diagnoses, allergies, procedures, recommendations, encounter events and demographics."""
from __future__ import annotations

import re

from backend.app.layer2_extraction import terminology
from backend.app.layer2_extraction.contracts import (AllergyDetails, Coding, DemographicDetails, DiagnosisDetails,
                                                     EncounterDetails, ProcedureDetails, RecommendationDetails)
from backend.app.layer2_extraction.dates import find_dates
from backend.app.layer2_extraction.extractors.base import Candidate, local_laterality
from backend.app.layer2_extraction.passage_view import PassageView

ICD10 = "http://hl7.org/fhir/sid/icd-10"
_STATUS_PREFIX = re.compile(r"^\s*(?:Vd\.\s?a\.|V\.\s?a\.|St\.\s?p\.|Z\.\s?n\.|Verdacht\s+auf)\s*", re.I)
_SALUTATION = re.compile(r"^\s*(?:Sehr\s+geehrte|Wir\s+berichten|Mit\s+(?:freundlichen|kollegialen)\s+Grüßen|Liebe)", re.I)
_SIGNATURE = re.compile(r"^\s*(?:Mit\s+(?:freundlichen|kollegialen)\s+Grüßen|ARZT\b|OA\b|Dr\.?\s|Prim\.|Befund(?:et)?:|Vidiert:)", re.I)


def _icd(m) -> tuple[Coding, ...]:
    e = m.entry
    if not e.get("icd10"):
        return ()
    return (Coding(system=ICD10, code=e["icd10"], display=e["display"], mapping_source=m.version,
                   level=e.get("level", "specific")),)


def _list_items_before_salutation(view: PassageView) -> bool:
    """True if the passage is in the list part of its section (before letter prose starts)."""
    seen_salutation = False
    for p in view.ingested.passages:
        if p.section_title != view.passage.section_title or p.section != view.passage.section:
            continue
        if p.normalized_start >= view.passage.normalized_start:
            break
        if _SALUTATION.search(p.display_text):
            seen_salutation = True
    return not seen_salutation and not _SALUTATION.search(view.passage.display_text)


_LEAD_NEGATION = re.compile(r"\s*(?:kein(?:e|en|er|es)?|ohne|nicht|ausschluss\s+(?:einer?|von))\s+", re.I)


def diagnoses(view: PassageView) -> list[Candidate]:
    p, text = view.passage, view.text
    if p.passage_type in ("table_header", "medication_row"):
        return []
    in_list = p.section == "diagnoses" and p.passage_type != "section_heading" and _list_items_before_salutation(view)
    matches = terminology.diagnoses(text)
    out = []
    if in_list:
        prefix = _STATUS_PREFIX.match(text)
        body_start = prefix.end() if prefix else 0
        lead_neg = _LEAD_NEGATION.match(text, body_start)
        if lead_neg:  # "Kein X" as a list item: keep the trigger outside the target so ConText can negate it
            body_start = lead_neg.end()
        if not matches:
            out.append(Candidate(view, 0, len(text), "diagnosis", text.strip(),
                                 DiagnosisDetails(text=text.strip(), laterality=local_laterality(text, 0, len(text)),
                                                  listed_in_diagnosis_section=True),
                                 target=(body_start, len(text)), notes=["no terminology match; uncoded"]))
        for m in matches:
            label = text.strip() if len(matches) == 1 else text[m.start:m.end]
            out.append(Candidate(view, 0 if len(matches) == 1 else m.start, len(text) if len(matches) == 1 else m.end,
                                 "diagnosis", label,
                                 DiagnosisDetails(text=text[m.start:m.end], laterality=local_laterality(text, m.start, m.end),
                                                  listed_in_diagnosis_section=True),
                                 _icd(m), target=(m.start, m.end)))
        return out
    for m in matches:
        out.append(Candidate(view, m.start, m.end, "diagnosis", text[m.start:m.end],
                             DiagnosisDetails(text=text[m.start:m.end], laterality=local_laterality(text, m.start, m.end)),
                             _icd(m)))
    return out


_ALLERGY_MENTION = re.compile(r"(?:[\wÄÖÜäöü]+-)?Allergie\b(?!\s*:)|\ballergisch\w*|\bUnverträglichkeit\w*", re.I)
_NO_ALLERGY = re.compile(r"^\s*(?:keine?|nicht)\b", re.I)


def _reactions(text: str, after: int) -> tuple[str, ...]:
    rest = text[after:]
    m = re.match(r"\s*\(([^)]*)\)", rest) or re.match(r"\s*mit\s+(.+?)(?=\s+bei\b|[.;)]|$)", rest)
    if not m:
        return ()
    return tuple(x.strip() for x in re.split(r",|\bund\b", m[1]) if x.strip())


def allergies(view: PassageView) -> list[Candidate]:
    p, text = view.passage, view.text
    if p.passage_type == "section_heading":
        return []
    out = []
    if p.section == "allergies" and _list_items_before_salutation(view):
        if _NO_ALLERGY.match(text):
            first = re.match(r"\s*\S+\s*", text).end()
            return [Candidate(view, 0, len(text), "allergy", text.strip(), AllergyDetails(substance_text=text.strip()),
                              target=(first, len(text.rstrip(" .;!"))) if first < len(text.rstrip(" .;!")) else None,
                              notes=["documented absence of allergies"])]
        sub = terminology.allergens(text)
        mm = _ALLERGY_MENTION.search(text)
        return [Candidate(view, 0, len(text), "allergy", text.strip(),
                          AllergyDetails(substance_text=text[sub[0].start:sub[0].end] if sub else text.strip(),
                                         substance=sub[0].entry["substance"] if sub else None,
                                         reactions=_reactions(text, mm.end()) if mm else _reactions(text, len(text))),
                          target=(mm.start(), mm.end()) if mm else None)]
    for mm in _ALLERGY_MENTION.finditer(text):
        sub = terminology.allergens(mm[0])
        out.append(Candidate(view, mm.start(), mm.end(), "allergy", mm[0],
                             AllergyDetails(substance_text=mm[0], substance=sub[0].entry["substance"] if sub else None,
                                            reactions=_reactions(text, mm.end()))))
    return out


def procedures(view: PassageView) -> list[Candidate]:
    text = view.text
    if view.passage.passage_type in ("table_header", "medication_row"):
        return []
    out = []
    for m in terminology.procedures(text):
        out.append(Candidate(view, m.start, m.end, "procedure", m.entry["display"],
                             ProcedureDetails(text=text[m.start:m.end], laterality=local_laterality(text, m.start, m.end)),
                             notes=["status inferred from ConText modifiers and section"]))
    return out


_REC_CUE = re.compile(r"empfohlen|empfehlen|sollte[n]?\b|geplant|terminisiert|vorgesehen|\bwird\s+(?:\w+\s+){0,4}besprochen"
                      r"|Kontrolle[n]?\b|(?:in|nach)\s+\d+\s+(?:Tagen|Wochen|Monaten)", re.I)
_QUESTION = re.compile(r"^\s*(?:Fragestellung|Frage)\s*:", re.I)


def recommendations(view: PassageView) -> list[Candidate]:
    p, text = view.passage, view.text
    if p.passage_type != "sentence" or _QUESTION.match(text) or _SIGNATURE.match(text):
        return []
    if not (_REC_CUE.search(text) or p.section == "plan"):
        return []
    actions = sorted({m.entry["display"] for m in terminology.procedures(text)})
    due = next((d.text for d in find_dates(text) if d.valid), None)
    rel = re.search(r"(?:in|nach)\s+\d+\s+(?:Tagen|Wochen|Monaten|Jahren)", text)
    return [Candidate(view, 0, len(text), "recommendation", re.sub(r"\s+", " ", text).strip(),
                      RecommendationDetails(text=re.sub(r"\s+", " ", text).strip(), action=", ".join(actions) or None,
                                            due_text=due or (rel[0] if rel else None)),
                      use_context=False, assertion_override={"temporality": "future"})]


_ENC = [
    ("admission", re.compile(r"\bAufnahme\s+am\s*$|\baufgenommen\b|\bStationäre\s+Aufnahme\b", re.I)),
    ("discharge", re.compile(r"\bEntlassen\s+am\s*$|\bentlassen\b", re.I)),
    ("visit", re.compile(r"\bin\s+Behandlung\s+war\b", re.I)),
    ("sample_taken", re.compile(r"\bEntnahmedatum\s*:\s*$", re.I)),
]


_CASE = re.compile(r"\bFall(?:-ID|zahl|nummer)?\s*:\s*(\d{4,})")


def encounters(view: PassageView) -> list[Candidate]:
    text, out = view.text, []
    if view.passage.passage_type in ("section_heading", "table_header"):
        return []
    for m in _CASE.finditer(text):
        out.append(Candidate(view, m.start(), m.end(), "encounter_event", f"case number: {m[1]}",
                             EncounterDetails(event="case_id", date_text=m[1], date_valid=True), use_context=False,
                             value_spans=[m.span(1)]))
    for d in find_dates(text):
        if re.search(r"geb\.?\s*(?:am\s*)?$", text[:d.start]):
            continue
        before, after = text[max(0, d.start - 40):d.start], text[d.end:]
        for kind, rx in _ENC:
            local_before = re.split(r"[|]", before)[-1]
            sentence_after = re.split(r"[.|]\s", after, maxsplit=1)[0]
            if rx.search(local_before) or (kind in ("admission", "discharge", "visit") and rx.search(sentence_after)
                                            and not any(r.search(sentence_after) for k, r in _ENC if k != kind and k != "sample_taken")):
                out.append(Candidate(view, d.start, d.end, "encounter_event", f"{kind}: {d.text}",
                                     EncounterDetails(event=kind, date_text=d.text, date_valid=d.valid),
                                     notes=[] if d.valid else ["malformed or impossible date in source"],
                                     needs_review=not d.valid))
                break
    return out


_DOB = re.compile(r"geb\.?\s*(?:am\s+)?(\d{1,2}\.\d{1,2}\.\d{4})", re.I)
_AGE = re.compile(r"\b(\d{1,3})-jährige[rn]?\b")


def demographics(view: PassageView) -> list[Candidate]:
    text, out = view.text, []
    for m in _DOB.finditer(text):
        d = find_dates(m[1])
        out.append(Candidate(view, m.start(), m.end(), "demographic", f"birth date: {m[1]}",
                             DemographicDetails(attribute="birth_date", value=d[0].value or m[1]), use_context=False,
                             value_spans=[m.span(1)]))
    for m in _AGE.finditer(text):
        out.append(Candidate(view, m.start(), m.end(), "demographic", f"age: {m[1]} years",
                             DemographicDetails(attribute="age_years", value=m[1]), use_context=False))
    return out


def extract(view: PassageView) -> list[Candidate]:
    return (diagnoses(view) + allergies(view) + procedures(view) + recommendations(view)
            + encounters(view) + demographics(view))
