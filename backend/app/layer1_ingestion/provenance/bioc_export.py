"""BioC interchange output with offsets relative to unchanged original source.

bioc package is used when installed; fallback serializes the same BioC-JSON fields
with the standard library so a no-network installation remains useful.
"""
from typing import Iterable
import json
from backend.app.shared.contracts.evidence import IngestedDocument


def as_bioc_collection(records: Iterable[IngestedDocument]) -> dict:
    documents = []
    for item in records:
        source = item.document
        documents.append({
            "id": source.source_id,
            "infons": {"patient_id": source.patient_id, "document_id": source.document_id,
                       "source_namespace": source.source_namespace,
                       "document_date": source.document_date or "", "document_version": source.document_version,
                       "source_sha256": source.source_hash, "offset_unit": "unicode_codepoints",
                       "source_format": source.source_format},
            "passages": [{
                "offset": p.original_start,
                "infons": {"passage_id": p.passage_id, "passage_type": p.passage_type,
                           "section": p.section or "", "section_title": p.section_title or "",
                           "length": str(p.original_end - p.original_start)},
                "text": p.raw_text,
                "sentences": [], "annotations": [], "relations": [],
            } for p in item.passages],
            "relations": [],
        })
    return {"source": "clinical-ai-platform-layer1", "date": "", "key": "",
            "infons": {"offset_unit": "unicode_codepoints"}, "documents": documents}


def dumps_bioc(records: Iterable[IngestedDocument]) -> str:
    payload = as_bioc_collection(records)
    try:
        # Use actual library when available; verifies BioC shape before exporting.
        from bioc import biocjson
        decoded = biocjson.loads(json.dumps(payload, ensure_ascii=False))
        return biocjson.dumps(decoded, indent=2)
    except ImportError:
        return json.dumps(payload, indent=2, ensure_ascii=False)
