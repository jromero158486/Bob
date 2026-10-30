"""Provenance checks for Layer 2 facts (structure only, not clinical correctness)."""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

from backend.app.layer2_extraction.contracts import ClinicalFact
from backend.app.shared.contracts.evidence import IngestedDocument


class FactProvenanceError(ValueError):
    pass


def verify_facts(facts: Iterable[ClinicalFact], records: Iterable[IngestedDocument]) -> int:
    by_source = {r.document.source_id: r for r in records}
    n = 0
    for f in facts:
        if not f.evidence:
            raise FactProvenanceError(f"{f.fact_id}: no evidence")
        for ev in f.evidence:
            rec = by_source.get(ev.source_id)
            if rec is None:
                raise FactProvenanceError(f"{f.fact_id}: unknown source {ev.source_id}")
            doc = rec.document
            if ev.patient_id != f.patient_id or doc.patient_id != f.patient_id:
                raise FactProvenanceError(f"{f.fact_id}: cross-patient evidence")
            if ev.source_sha256 != doc.source_hash or hashlib.sha256(doc.original_text.encode()).hexdigest() != doc.source_hash:
                raise FactProvenanceError(f"{f.fact_id}: checksum mismatch")
            if doc.original_text[ev.original_start:ev.original_end] != ev.raw_text:
                raise FactProvenanceError(f"{f.fact_id}: evidence text does not match source offsets")
            if not any(p.passage_id == ev.passage_id and p.original_start <= ev.original_start
                       and ev.original_end <= p.original_end for p in rec.passages):
                raise FactProvenanceError(f"{f.fact_id}: evidence outside its passage")
            n += 1
    return n
