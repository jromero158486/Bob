"""Optional LLM extraction of narrative relations, grounded by exact quotes.

The LLM may only *propose* facts. Each proposal must cite a passage_id that was
sent and a verbatim quote from that passage; otherwise it is rejected. Accepted
proposals are marked needs_review: valid JSON is not evidence of correctness.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from backend.app.layer2_extraction.contracts import (ComponentRun, DiagnosisDetails, ExtractorInfo, MedicationDetails,
                                                     ProcedureDetails, RecommendationDetails)
from backend.app.layer2_extraction import terminology
from backend.app.layer2_extraction.extractors.base import Candidate
from backend.app.layer2_extraction.extractors.clinical import _icd
from backend.app.layer2_extraction.extractors.medication import _coding as _atc
from backend.app.layer2_extraction.llm.provider import LLMProvider, LLMUnavailable
from backend.app.layer2_extraction.passage_view import PassageView

NARRATIVE_SECTIONS = {"clinical_course", "history", "plan", "clinical_findings", None, "unclassified"}


class LLMFactProposal(BaseModel):
    passage_ref: int = Field(description="Index of the passage in the request")
    quote: str = Field(description="Verbatim substring of that passage supporting the fact")
    fact_type: Literal["medication", "diagnosis", "procedure", "recommendation"]
    label: str
    relation: str | None = Field(None, description="e.g. 'medication started because of carotid stenosis'")


class LLMExtraction(BaseModel):
    facts: list[LLMFactProposal]


SYSTEM = ("You extract clinical facts from German clinical letter passages. Only report facts explicitly stated. "
          "For every fact give passage_ref and an exact verbatim quote copied from that passage. "
          "Do not translate the quote. If nothing is stated, return an empty list.")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def candidate_codings(fact_type: str, text: str) -> tuple:
    """Terminology candidates for an LLM span from the local lexicons; always unverified (fact needs_review)."""
    if fact_type == "diagnosis":
        hits = terminology.diagnoses(text)
        codings = _icd(hits[0]) if hits else ()
    elif fact_type == "medication":
        codings = _atc(terminology.medication_by_name(text))
    else:
        return ()
    return tuple(c.model_copy(update={"mapping_source": f"{c.mapping_source}; candidate from LLM span"}) for c in codings)


def ground(proposal: LLMFactProposal, views: list[PassageView]) -> tuple[PassageView, int, int] | None:
    if not 0 <= proposal.passage_ref < len(views):
        return None
    v = views[proposal.passage_ref]
    q = _norm(proposal.quote)
    if not q:
        return None
    # Whitespace-tolerant exact match against the passage's readable text.
    rx = re.compile(r"\s+".join(map(re.escape, q.split(" "))))
    m = rx.search(v.text)
    return (v, m.start(), m.end()) if m else None


def llm_candidates(all_views: list[PassageView], provider: LLMProvider, batch: int = 25):
    narrative = [v for v in all_views if v.passage.passage_type == "sentence" and v.passage.section in NARRATIVE_SECTIONS
                 and len(v.text) > 40]
    info = ExtractorInfo(name=f"llm:{provider.name}", version=provider.model)
    out: dict[int, list[Candidate]] = {}
    index = {id(v): i for i, v in enumerate(all_views)}
    accepted = rejected = 0
    try:
        for k in range(0, len(narrative), batch):
            chunk = narrative[k:k + batch]
            user = "\n".join(f"[{i}] {_norm(v.text)}" for i, v in enumerate(chunk))
            resp = provider.complete_json(SYSTEM, user, LLMExtraction.model_json_schema(), "clinical_facts")
            info = ExtractorInfo(name=f"llm:{resp.provider}", version=resp.model)
            try:
                parsed = LLMExtraction.model_validate(resp.data)
            except ValidationError:
                rejected += 1
                continue
            for prop in parsed.facts:
                g = ground(prop, chunk)
                if g is None:
                    rejected += 1
                    continue
                v, s, e = g
                details = {"medication": lambda: MedicationDetails(drug_text=v.text[s:e]),
                           "diagnosis": lambda: DiagnosisDetails(text=v.text[s:e]),
                           "procedure": lambda: ProcedureDetails(text=v.text[s:e]),
                           "recommendation": lambda: RecommendationDetails(text=v.text[s:e])}[prop.fact_type]()
                notes = ["LLM proposal grounded by verbatim quote; not verified"]
                if prop.relation:
                    notes.append(f"relation: {prop.relation}")
                codings = candidate_codings(prop.fact_type, v.text[s:e])
                out.setdefault(index[id(v)], []).append(Candidate(v, s, e, prop.fact_type, prop.label, details,
                                                                  codings=codings, extractor=info, needs_review=True,
                                                                  notes=notes))
                accepted += 1
    except LLMUnavailable as exc:
        # Facts accepted before the failure are kept (each is quote-grounded and needs_review) but reported as partial.
        status = "partial" if accepted else "failed"
        return out, ComponentRun(name="llm-structured-extraction", version=f"{info.name} {info.version}", status=status,
                                 detail=f"{exc}; accepted={accepted} rejected={rejected} before failure; "
                                        f"batches done={k // batch}/{-(-len(narrative) // batch)}")
    return out, ComponentRun(name="llm-structured-extraction", version=f"{info.name} {info.version}", status="ran",
                             detail=f"accepted={accepted} rejected={rejected}")
