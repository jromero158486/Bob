"""Layer 2 pipeline: Layer 1 IngestedDocument -> evidence-linked ClinicalFact candidates."""
from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable

from backend.app.layer2_extraction import context, terminology
from backend.app.layer2_extraction.contracts import (Assertion, ClinicalDate, ClinicalFact, ComponentRun,
                                                     ExtractionResult, ExtractionRun, ExtractorInfo, MedicationDetails,
                                                     make_fact_id)
from backend.app.layer2_extraction.dates import find_dates, relative_due
from backend.app.layer2_extraction.extractors import clinical, medication, observation
from backend.app.layer2_extraction.extractors.base import RULES, Candidate
from backend.app.layer2_extraction.ner.gernermed import GernermedNER, NerUnavailable
from backend.app.layer2_extraction.passage_view import PassageView, views
from backend.app.layer2_extraction.validation import verify_facts
from backend.app.shared.contracts.evidence import IngestedDocument

EXTRACTORS = (medication.extract, observation.extract, clinical.extract)


def _event_date(c: Candidate) -> ClinicalDate | None:
    text = c.view.text
    if c.fact_type == "encounter_event":
        d = next((d for d in find_dates(text) if d.start == c.start), None)
        return ClinicalDate(value=d.value, precision=d.precision, source="explicit_in_passage", text=d.text) if d and d.valid else None
    if c.fact_type == "demographic":
        return None
    dates = [d for d in find_dates(text) if d.valid and not re.search(r"geb\.?\s*(?:am\s*)?$", text[:d.start])]
    if dates:
        d = min(dates, key=lambda d: (abs(d.start - c.start), d.start < c.start))
        return ClinicalDate(value=d.value, precision=d.precision, source="explicit_in_passage", text=d.text)
    title_dates = [d for d in find_dates(c.view.passage.section_title or "") if d.valid]
    if title_dates and c.view.passage.passage_type != "section_heading":
        d = title_dates[0]
        return ClinicalDate(value=d.value, precision=d.precision, source="section_heading", text=d.text)
    if c.fact_type == "recommendation":
        rel = relative_due(text, c.view.passage.document_date)
        if rel:
            return ClinicalDate(value=rel[0], precision=rel[1], source="relative_to_document", text=text[rel[2]:rel[3]])
    return None


def _procedure_status(a: Assertion) -> str:
    if a.question or a.negated:
        return "mentioned"
    if a.temporality == "future":
        return "recommended" if any(re.search(r"empf|sollte", t.text, re.I) for t in a.triggers) else "planned"
    if a.temporality == "historical":
        return "historical"
    return "performed"


def _gernermed_candidates(view: PassageView, ents, existing: list[Candidate], info: ExtractorInfo) -> list[Candidate]:
    out = []
    for e in ents:
        if e.label != "Drug" or len(e.text.strip()) < 3 or e.text.strip().isdigit():
            continue
        overlapping = [c for c in existing if c.fact_type == "medication" and c.start < e.end and e.start < c.end]
        if overlapping:
            for c in overlapping:
                c.notes.append(f"supported:{info.name}")
            continue
        # GERNERMED++ alone over-labels header/abbreviation tokens in German letters (e.g. 'PLZ', 'ARZT').
        # A model-only candidate is kept only if the model also tags a dose attribute next to it.
        attrs = [s for s in ents if s.label in ("Strength", "Dosage", "Frequency")
                 and (0 <= s.start - e.end <= 25 or 0 <= e.start - s.end <= 15)]
        if not attrs:
            continue
        strength = next((s for s in ents if s.label == "Strength" and 0 <= s.start - e.end <= 3), None)
        lex = terminology.medication_by_name(e.text)
        m = re.match(r"(\d+(?:[.,]\d+)?)\s*(\w+)", strength.text) if strength else None
        det = MedicationDetails(drug_text=e.text, ingredient=lex.entry["ingredient"] if lex else None,
                                strength_value=float(m[1].replace(",", ".")) if m else None,
                                strength_unit=m[2] if m else None, statement="mentioned")
        end = strength.end if strength else e.end
        out.append(Candidate(view, e.start, end, "medication", view.text[e.start:end], det, medication._coding(lex),
                             extractor=info, needs_review=True,
                             notes=["GERNERMED++ candidate without deterministic rule support"]))
    return out


def extract(records: Iterable[IngestedDocument], *, context_engine: str = "native",
            ner: GernermedNER | None = None, llm=None) -> ExtractionResult:
    records = list(records)
    run = ExtractionRun(run_id="run:" + uuid.uuid4().hex[:12],
                        patient_ids=sorted({r.document.patient_id for r in records}),
                        document_ids=[r.document.document_id for r in records],
                        resource_checksums=terminology.resource_checksums())
    run.components.append(ComponentRun(name="layer1-sectionizer", version=",".join(sorted({r.section_engine for r in records})), status="ran"))
    run.components.append(ComponentRun(name=RULES.name, version=RULES.version, status="ran"))
    run.components.append(ComponentRun(name=f"context-{context_engine}", version=context.rules_version(), status="ran"))
    all_views = [v for r in records for v in views(r)]
    cands: dict[int, list[Candidate]] = defaultdict(list)
    for i, v in enumerate(all_views):
        for fn in EXTRACTORS:
            cands[i].extend(fn(v))
    if ner is None:
        run.components.append(ComponentRun(name="gernermed++", version="-", status="disabled",
                                           detail="GERNERMED_PYTHON not configured"))
    else:
        try:
            ents = ner.annotate([v.text for v in all_views])
            info = ExtractorInfo(name="gernermed++", version=ner.version)
            for i, v in enumerate(all_views):
                if v.passage.passage_type in ("sentence", "medication_row"):
                    cands[i].extend(_gernermed_candidates(v, ents[i], cands[i], info))
            n_drug = sum(1 for es in ents for x in es if x.label == "Drug")
            run.components.append(ComponentRun(name="gernermed++", version=ner.version, status="ran",
                                               detail=f"license: {ner.meta.get('license')}; raw Drug entities: {n_drug}"))
        except (NerUnavailable, OSError, ValueError) as exc:
            run.components.append(ComponentRun(name="gernermed++", version=ner.model, status="failed", detail=str(exc)))
            run.warnings.append(f"GERNERMED++ failed: {exc}")
    if llm is not None:
        from backend.app.layer2_extraction.llm.structured_extraction import llm_candidates
        llm_out, comp = llm_candidates(all_views, llm)
        run.components.append(comp)
        for i, extra in llm_out.items():
            cands[i].extend(extra)
    else:
        run.components.append(ComponentRun(name="llm-structured-extraction", version="-", status="disabled",
                                           detail="no LLM provider passed"))

    facts: dict[str, ClinicalFact] = {}
    for i, v in enumerate(all_views):
        cs = cands[i]
        ctx_targets = [c.target or (c.start, c.end) for c in cs if c.use_context]
        assertions = iter(context.classify(v.text, ctx_targets, context_engine))
        for c in cs:
            a = next(assertions) if c.use_context else Assertion(**(c.assertion_override or {}), engine="none")
            details = c.details
            event_date = _event_date(c)
            if c.fact_type == "procedure":
                status = _procedure_status(a)
                doc_date = v.passage.document_date
                if status == "performed" and (v.passage.section == "plan" or (
                        event_date and doc_date and event_date.value[:len(doc_date)] > doc_date[:len(event_date.value)])):
                    status = "planned"  # plan section, or event dated after the document itself
                details = details.model_copy(update={"status": status})
            mention = v.span(c.start, c.end, "mention")
            evidence = [mention] + [v.span(s, e, "value") for s, e in c.value_spans
                                    if (s, e) != (c.start, c.end) and e > s]
            evidence += [v.span(t.passage_offset, t.passage_offset + len(t.text), "context_trigger") for t in a.triggers]
            support = tuple(ExtractorInfo(name=n.split(":", 1)[1], version="see run")
                            for n in dict.fromkeys(x for x in c.notes if x.startswith("supported:")))
            notes = tuple(x for x in c.notes if not x.startswith("supported:"))
            fid = make_fact_id(v.passage.patient_id, v.passage.document_id, v.passage.source_sha256, c.fact_type,
                               mention.original_start, mention.original_end, c.label, c.extractor.name)
            facts[fid] = ClinicalFact(
                fact_id=fid, fact_type=c.fact_type, patient_id=v.passage.patient_id, document_id=v.passage.document_id,
                source_id=v.passage.source_id, label=c.label, details=details, codings=c.codings, assertion=a,
                event_date=event_date, document_date=v.passage.document_date, section=v.passage.section,
                evidence=tuple(evidence), extractor=c.extractor, supporting_extractors=support,
                review_status="needs_review" if c.needs_review else "unreviewed", notes=notes)
    out = list(facts.values())
    verify_facts(out, records)
    run.fact_counts = dict(Counter(f.fact_type for f in out))
    return ExtractionResult(run=run, facts=out)
