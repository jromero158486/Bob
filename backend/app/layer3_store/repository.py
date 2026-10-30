"""Layer 3 repository: source-aware incremental ingest and patient-scoped temporal queries.

Every read method takes patient_id explicitly; there is no cross-patient query API.
"as_of" means "as documented up to that date" (document_date <= as_of), so later
documents can never leak into an earlier clinical view.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.engine import Engine

from backend.app.layer2_extraction.contracts import ClinicalFact, ExtractionResult
from backend.app.layer3_store.db import session_factory
from backend.app.layer3_store.models import (Document, Encounter, EvidenceRow, ExtractionRunRow, Fact, Passage, Patient,
                                             ReviewEvent, ReviewItem)
from backend.app.shared.contracts.evidence import IngestedDocument

REVIEW_STATES = ("pending", "accepted", "rejected", "needs_more_info")


@dataclass
class IngestReport:
    new_documents: list[str] = field(default_factory=list)
    unchanged_documents: list[str] = field(default_factory=list)
    superseded_documents: list[str] = field(default_factory=list)
    facts_added: int = 0


def _date_le(value: str | None, as_of: str | None) -> bool:
    if as_of is None or value is None:
        return True
    n = min(len(value), len(as_of))
    return value[:n] <= as_of[:n]


def to_fact(row: Fact) -> ClinicalFact:
    return ClinicalFact.model_validate({
        "fact_id": row.fact_id, "fact_type": row.fact_type, "patient_id": row.patient_id,
        "document_id": row.document_id, "source_id": row.source_id, "label": row.label, "details": row.details,
        "codings": row.codings, "assertion": row.assertion,
        "event_date": ({"value": row.event_date, "precision": row.event_date_precision, "source": row.event_date_source}
                       if row.event_date else None),
        "document_date": row.document_date, "section": row.section,
        "evidence": [{"patient_id": e.patient_id, "document_id": row.document_id, "source_id": e.source_id,
                      "source_sha256": e.source_sha256, "passage_id": e.passage_id, "original_start": e.original_start,
                      "original_end": e.original_end, "raw_text": e.raw_text, "display_text": e.display_text,
                      "role": e.role} for e in row.evidence],
        "extractor": {"name": row.extractor_name, "version": row.extractor_version},
        "supporting_extractors": [{"name": n, "version": "see run"} for n in row.notes if False] or [],
        "review_status": row.review_status, "notes": [n for n in row.notes if not n.startswith("support:")],
    })


class ClinicalStore:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.Session = session_factory(engine)

    # ---------- ingest ----------
    def ingest(self, records: Iterable[IngestedDocument], result: ExtractionResult) -> IngestReport:
        records = list(records)
        report = IngestReport()
        with self.Session.begin() as s:
            new_sources: set[str] = set()
            for rec in records:
                d = rec.document
                if s.get(Patient, d.patient_id) is None:
                    s.add(Patient(patient_id=d.patient_id, source_namespace=d.source_namespace))
                    s.flush()
                if s.get(Document, d.source_id) is not None:
                    report.unchanged_documents.append(d.source_id)
                    continue
                for old in s.scalars(select(Document).where(Document.patient_id == d.patient_id,
                                                            Document.document_id == d.document_id,
                                                            Document.is_current.is_(True))):
                    old.is_current, old.superseded_by = False, d.source_id
                    report.superseded_documents.append(old.source_id)
                enc_key = None
                if d.encounter_id:
                    enc_key = f"{d.patient_id}:{d.encounter_id}"
                    if s.get(Encounter, enc_key) is None:
                        adm = d.metadata.get("admission") if isinstance(d.metadata.get("admission"), dict) else {}
                        s.add(Encounter(encounter_key=enc_key, patient_id=d.patient_id, source_encounter_id=d.encounter_id,
                                        kind=adm.get("type"), metadata_json=adm))
                        s.flush()
                s.add(Document(source_id=d.source_id, patient_id=d.patient_id, document_id=d.document_id,
                               document_version=d.document_version, source_sha256=d.source_hash,
                               source_format=d.source_format, source_namespace=d.source_namespace,
                               title=d.document_title, document_date=d.document_date, document_type=d.document_type,
                               hospital=d.hospital, encounter_key=enc_key, original_text=d.original_text,
                               normalized_text=rec.normalized_text, section_engine=rec.section_engine,
                               metadata_json=d.metadata))
                s.flush()
                s.add_all(Passage(passage_id=p.passage_id, patient_id=p.patient_id, source_id=p.source_id,
                                  passage_type=p.passage_type, section=p.section, section_title=p.section_title,
                                  original_start=p.original_start, original_end=p.original_end,
                                  normalized_start=p.normalized_start, normalized_end=p.normalized_end,
                                  raw_text=p.raw_text, display_text=p.display_text) for p in rec.passages)
                new_sources.add(d.source_id)
                report.new_documents.append(d.source_id)
            s.flush()
            facts = [f for f in result.facts if f.source_id in new_sources]
            if facts and s.get(ExtractionRunRow, result.run.run_id) is None:
                s.add(ExtractionRunRow(run_id=result.run.run_id, started_at=result.run.started_at,
                                       payload=result.run.model_dump(mode="json")))
                s.flush()
            for f in facts:
                det = f.details.model_dump(mode="json")
                concept = det.get("name") or det.get("ingredient") or (f.codings[0].display if f.codings else None)
                row = Fact(fact_id=f.fact_id, patient_id=f.patient_id, source_id=f.source_id, document_id=f.document_id,
                           fact_type=f.fact_type, label=f.label, concept=concept,
                           primary_code=f.codings[0].code if f.codings else None, details=det,
                           codings=[c.model_dump(mode="json") for c in f.codings],
                           assertion=f.assertion.model_dump(mode="json"), negated=f.assertion.negated,
                           certainty=f.assertion.certainty, temporality=f.assertion.temporality,
                           experiencer=f.assertion.experiencer, question=f.assertion.question,
                           event_date=f.event_date.value if f.event_date else None,
                           event_date_precision=f.event_date.precision if f.event_date else None,
                           event_date_source=f.event_date.source if f.event_date else None,
                           document_date=f.document_date, section=f.section, extractor_name=f.extractor.name,
                           extractor_version=f.extractor.version, review_status=f.review_status,
                           notes=list(f.notes) + [f"support:{x.name}" for x in f.supporting_extractors],
                           run_id=result.run.run_id)
                row.evidence = [EvidenceRow(patient_id=e.patient_id, source_id=e.source_id, passage_id=e.passage_id,
                                            source_sha256=e.source_sha256, original_start=e.original_start,
                                            original_end=e.original_end, raw_text=e.raw_text,
                                            display_text=e.display_text, role=e.role) for e in f.evidence]
                s.add(row)
            report.facts_added = len(facts)
        return report

    # ---------- reads (always patient-scoped) ----------
    def patients(self) -> list[dict]:
        with self.Session() as s:
            out = []
            for p in s.scalars(select(Patient).order_by(Patient.patient_id)):
                docs = s.scalars(select(Document).where(Document.patient_id == p.patient_id,
                                                        Document.is_current.is_(True))).all()
                dates = sorted(d.document_date for d in docs if d.document_date)
                out.append({"patient_id": p.patient_id, "display_name": p.display_name, "document_count": len(docs),
                            "first_document_date": dates[0] if dates else None,
                            "last_document_date": dates[-1] if dates else None})
            return out

    def documents(self, patient_id: str, include_superseded: bool = False) -> list[Document]:
        with self.Session() as s:
            q = select(Document).where(Document.patient_id == patient_id)
            if not include_superseded:
                q = q.where(Document.is_current.is_(True))
            return list(s.scalars(q.order_by(Document.document_date, Document.document_id)))

    def document(self, patient_id: str, document_id: str) -> tuple[Document, list[Passage]] | None:
        with self.Session() as s:
            d = s.scalars(select(Document).where(Document.patient_id == patient_id, Document.document_id == document_id,
                                                 Document.is_current.is_(True))).first()
            if d is None:
                return None
            return d, list(d.passages)

    def source_version(self, source_id: str) -> Document | None:
        """Unscoped lookup by exact source version. Only for integrity checks; callers must compare patient_id."""
        with self.Session() as s:
            return s.get(Document, source_id)

    def passage_by_id(self, passage_id: str) -> Passage | None:
        """Unscoped lookup for integrity checks; callers must compare patient_id/source_id."""
        with self.Session() as s:
            return s.get(Passage, passage_id)

    def passages(self, patient_id: str, passage_ids: Iterable[str]) -> dict[str, Passage]:
        ids = list(set(passage_ids))
        if not ids:
            return {}
        with self.Session() as s:
            return {p.passage_id: p for p in s.scalars(select(Passage).where(Passage.patient_id == patient_id,
                                                                             Passage.passage_id.in_(ids)))}

    def facts(self, patient_id: str, *, types: Iterable[str] | None = None, as_of: str | None = None,
              code_prefixes: Iterable[str] | None = None, concepts: Iterable[str] | None = None,
              include_superseded: bool = False) -> list[ClinicalFact]:
        with self.Session() as s:
            q = select(Fact).join(Document, Document.source_id == Fact.source_id).where(Fact.patient_id == patient_id)
            if not include_superseded:
                q = q.where(Document.is_current.is_(True))
            if types:
                q = q.where(Fact.fact_type.in_(list(types)))
            if concepts:
                q = q.where(Fact.concept.in_(list(concepts)))
            rows = s.scalars(q.order_by(Fact.document_date, Fact.document_id, Fact.fact_id)).unique().all()
            out = []
            prefixes = tuple(code_prefixes or ())
            for r in rows:
                if not _date_le(r.document_date, as_of):
                    continue
                if prefixes and not any(c.get("code", "").startswith(prefixes) for c in r.codings):
                    continue
                out.append(to_fact(r))
            return out

    def observation_series(self, patient_id: str, name: str, as_of: str | None = None) -> list[ClinicalFact]:
        obs = [f for f in self.facts(patient_id, types=["observation"], concepts=[name], as_of=as_of)
               if not f.assertion.negated and not f.assertion.question]
        return sorted(obs, key=lambda f: ((f.event_date.value if f.event_date else None) or f.document_date or "",
                                          f.evidence[0].original_start))

    def latest_observation(self, patient_id: str, name: str, as_of: str | None = None) -> ClinicalFact | None:
        series = self.observation_series(patient_id, name, as_of)
        return series[-1] if series else None

    def medication_lists(self, patient_id: str, as_of: str | None = None) -> list[tuple[Document, list[ClinicalFact]]]:
        meds = [f for f in self.facts(patient_id, types=["medication"], as_of=as_of)
                if f.details.statement == "medication_list"]
        by_doc: dict[str, list[ClinicalFact]] = {}
        for f in meds:
            by_doc.setdefault(f.source_id, []).append(f)
        docs = {d.source_id: d for d in self.documents(patient_id)}
        lists = [(docs[sid], fs) for sid, fs in by_doc.items() if sid in docs]
        return sorted(lists, key=lambda x: (x[0].document_date or "", x[0].document_id))

    def medication_list(self, patient_id: str, as_of: str | None = None):
        lists = self.medication_lists(patient_id, as_of)
        return lists[-1] if lists else None

    @staticmethod
    def compare_medication_lists(before: list[ClinicalFact], after: list[ClinicalFact]) -> list[dict]:
        def key(f):
            return (f.details.ingredient or f.details.drug_text).casefold()

        def sig(f):
            d = f.details
            sched = d.schedule.model_dump(exclude={"text"}) if d.schedule else None
            return (d.strength_value, (d.strength_unit or "").casefold(), sched, (d.frequency_text or "").replace(" ", ""))
        a, b = {key(f): f for f in before}, {key(f): f for f in after}
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append({"change": "added", "drug": k, "after": b[k]})
            elif k not in b:
                out.append({"change": "removed", "drug": k, "before": a[k]})
            elif sig(a[k]) != sig(b[k]):
                out.append({"change": "changed", "drug": k, "before": a[k], "after": b[k]})
            else:
                out.append({"change": "unchanged", "drug": k, "before": a[k], "after": b[k]})
        return out

    def search_passages(self, patient_id: str, query: str, limit: int = 20) -> list[tuple[Passage, float]]:
        words = [w for w in re.findall(r"[\wÄÖÜäöüß]{3,}", query)]
        if not words:
            return []
        with self.Session() as s:
            if self.engine.dialect.name == "postgresql":
                expr = " | ".join(f"{w}:*" for w in words)
                rows = s.execute(text(
                    "SELECT p.passage_id, ts_rank(p.tsv, to_tsquery('german', :q)) AS score FROM passages p "
                    "JOIN documents d ON d.source_id = p.source_id AND d.is_current "
                    "WHERE p.patient_id = :pid AND p.tsv @@ to_tsquery('german', :q) "
                    "ORDER BY score DESC LIMIT :lim"), {"q": expr, "pid": patient_id, "lim": limit}).all()
                found = self.passages(patient_id, [r[0] for r in rows])
                return [(found[r[0]], float(r[1])) for r in rows if r[0] in found]
            q = (select(Passage).join(Document, Document.source_id == Passage.source_id)
                 .where(Passage.patient_id == patient_id, Document.is_current.is_(True)))
            scored = []
            lw = [w.casefold() for w in words]
            for p in s.scalars(q):
                t = p.display_text.casefold()
                score = sum(1 for w in lw if w in t)
                if score:
                    scored.append((p, score / len(lw)))
            return sorted(scored, key=lambda x: -x[1])[:limit]

    # ---------- human review ----------
    def upsert_review_item(self, patient_id: str, item_key: str, item_type: str, summary: str, payload: dict) -> dict:
        with self.Session.begin() as s:
            item = s.scalars(select(ReviewItem).where(ReviewItem.patient_id == patient_id,
                                                      ReviewItem.item_key == item_key)).first()
            if item is None:
                item = ReviewItem(patient_id=patient_id, item_key=item_key, item_type=item_type, summary=summary,
                                  payload=payload)
                s.add(item)
                s.flush()
            return {"id": item.id, "status": item.status}

    def set_review_status(self, patient_id: str, item_key: str, status: str, reviewer: str, comment: str | None = None):
        if status not in REVIEW_STATES:
            raise ValueError(f"Invalid review status {status}")
        from datetime import datetime, timezone
        with self.Session.begin() as s:
            item = s.scalars(select(ReviewItem).where(ReviewItem.patient_id == patient_id,
                                                      ReviewItem.item_key == item_key)).first()
            if item is None:
                raise KeyError(item_key)
            item.events.append(ReviewEvent(from_status=item.status, to_status=status, reviewer=reviewer, comment=comment))
            item.status, item.updated_at = status, datetime.now(timezone.utc)
            return {"id": item.id, "status": item.status}

    def review_items(self, patient_id: str) -> list[dict]:
        with self.Session() as s:
            items = s.scalars(select(ReviewItem).where(ReviewItem.patient_id == patient_id).order_by(ReviewItem.id)).all()
            return [{"item_key": i.item_key, "item_type": i.item_type, "status": i.status, "summary": i.summary,
                     "payload": i.payload, "updated_at": i.updated_at.isoformat(),
                     "history": [{"from": e.from_status, "to": e.to_status, "reviewer": e.reviewer,
                                  "comment": e.comment, "at": e.at.isoformat()} for e in i.events]} for i in items]
