"""Immutable cross-layer contracts. Offsets are Python Unicode codepoint indices.

No assertion of clinical truth is made by the ingestion layer.
"""
from dataclasses import dataclass, field
from typing import Any, Literal

PassageType = Literal[
    "section_heading", "sentence", "medication_row", "table_header",
    "observation_row", "other_row",
]


@dataclass(frozen=True)
class SourceDocument:
    patient_id: str
    document_id: str
    original_text: str
    source_hash: str  # SHA-256 of original UTF-8 text (not of normalized text)
    source_name: str
    source_format: str
    document_title: str
    document_date: str | None
    document_version: str
    document_type: str | None
    hospital: str | None
    encounter_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_namespace: str = "local"  # institution/system namespace prevents cross-source ID collisions

    @property
    def source_id(self) -> str:
        return f"{self.source_namespace}:{self.patient_id}:{self.document_id}:{self.document_version}:{self.source_hash[:16]}"


@dataclass(frozen=True)
class EvidencePassage:
    patient_id: str
    document_id: str
    source_id: str
    source_sha256: str
    passage_id: str
    passage_type: PassageType
    section: str | None
    section_title: str | None
    original_start: int
    original_end: int
    normalized_start: int
    normalized_end: int
    raw_text: str
    display_text: str
    document_title: str
    document_date: str | None
    document_type: str | None
    document_version: str
    hospital: str | None
    encounter_id: str | None


@dataclass(frozen=True)
class IngestedDocument:
    document: SourceDocument
    passages: tuple[EvidencePassage, ...]
    normalized_text: str
    # Boundary map to raw source text: each normalized codepoint maps to [start, end)
    source_spans: tuple[tuple[int, int], ...]
    section_engine: str
