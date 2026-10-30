"""Integrity checks for immutable clinical source references."""
import hashlib
from backend.app.shared.contracts.evidence import IngestedDocument, EvidencePassage


class ProvenanceError(ValueError):
    pass


def verify_ingested(ingested: IngestedDocument, coverage: bool = True) -> dict[str, int]:
    doc = ingested.document
    text = ingested.normalized_text
    raw = doc.original_text
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != doc.source_hash:
        raise ProvenanceError("Original source hash mismatch")
    if len(ingested.source_spans) != len(text):
        raise ProvenanceError("Projection mapping length mismatch")
    visited = set()
    covered = [False] * len(text)
    for p in ingested.passages:
        if p.passage_id in visited:
            raise ProvenanceError("Duplicate passage ID")
        visited.add(p.passage_id)
        if p.document_id != doc.document_id or p.patient_id != doc.patient_id or p.source_id != doc.source_id:
            raise ProvenanceError("Cross-patient/document provenance mismatch")
        if p.source_sha256 != doc.source_hash:
            raise ProvenanceError("Outdated source checksum")
        if not (0 <= p.original_start < p.original_end <= len(raw)):
            raise ProvenanceError("Invalid source offsets")
        if raw[p.original_start:p.original_end] != p.raw_text:
            raise ProvenanceError("Passage does not match exact original slice")
        if not (0 <= p.normalized_start < p.normalized_end <= len(text)):
            raise ProvenanceError("Invalid normalized offsets")
        a = ingested.source_spans[p.normalized_start][0]
        b = ingested.source_spans[p.normalized_end - 1][1]
        if (a, b) != (p.original_start, p.original_end):
            raise ProvenanceError("Source-to-display map mismatch")
        for i in range(p.normalized_start, p.normalized_end):
            covered[i] = True
    uncovered = sum(1 for i, ch in enumerate(text) if not ch.isspace() and not covered[i])
    if coverage and uncovered:
        raise ProvenanceError(f"Uncovered normalized content: {uncovered} characters")
    return {"passages": len(visited), "uncovered_visible_characters": uncovered}


def verify_passage_reference(p: EvidencePassage, original_text: str) -> bool:
    return (hashlib.sha256(original_text.encode("utf-8")).hexdigest() == p.source_sha256
            and original_text[p.original_start:p.original_end] == p.raw_text)
