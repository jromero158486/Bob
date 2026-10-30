"""Layer 1 end-to-end API, intentionally independent of any clinical LLM."""
from collections.abc import Iterable
import re
from backend.app.layer1_ingestion.processing.segmentation import segment
from backend.app.layer1_ingestion.processing.source_mapping import project_source
from backend.app.layer1_ingestion.provenance.validator import verify_ingested
from backend.app.shared.contracts.evidence import SourceDocument, EvidencePassage, IngestedDocument


def process_document(source: SourceDocument, engine: str = "auto") -> IngestedDocument:
    projection = project_source(source.original_text)
    segments, used_engine = segment(projection, engine)
    passages = []
    for p in segments:
        start, end = projection.original_bounds(p.start, p.end)
        # Include the original markup/internal breaks, never the transformed text.
        raw = source.original_text[start:end]
        display = re.sub(r"\s+", " ", projection.text[p.start:p.end]).strip()
        passages.append(EvidencePassage(
            patient_id=source.patient_id, document_id=source.document_id,
            source_id=source.source_id, source_sha256=source.source_hash,
            passage_id=f"{source.source_id}:span:{start}:{end}",
            passage_type=p.passage_type,
            section=p.section, section_title=p.section_title,
            original_start=start, original_end=end,
            normalized_start=p.start, normalized_end=p.end,
            raw_text=raw, display_text=display,
            document_title=source.document_title, document_date=source.document_date,
            document_type=source.document_type, document_version=source.document_version,
            hospital=source.hospital, encounter_id=source.encounter_id,
        ))
    out = IngestedDocument(source, tuple(passages), projection.text, projection.spans, used_engine)
    verify_ingested(out)
    return out


def ingest_documents(documents: Iterable[SourceDocument], engine: str = "auto") -> list[IngestedDocument]:
    records = [process_document(doc, engine=engine) for doc in documents]
    ids = [d.document.source_id for d in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate patient/document/version/content source ID")
    return records


def search_passages(records: Iterable[IngestedDocument], query: str, limit: int = 30) -> list[EvidencePassage]:
    """Literal inspection only, not semantic clinical search."""
    q = query.strip().casefold()
    if not q:
        return []
    return [p for d in records for p in d.passages if q in p.display_text.casefold()][:limit]
