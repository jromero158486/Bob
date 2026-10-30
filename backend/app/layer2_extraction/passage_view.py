"""Map extractor offsets inside a passage back to exact original source offsets."""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.layer2_extraction.contracts import EvidenceSpan
from backend.app.shared.contracts.evidence import EvidencePassage, IngestedDocument


@dataclass(frozen=True)
class PassageView:
    """Readable passage text (BR/entities resolved, line breaks kept) with a source map."""
    passage: EvidencePassage
    ingested: IngestedDocument

    @property
    def text(self) -> str:
        p = self.passage
        return self.ingested.normalized_text[p.normalized_start:p.normalized_end]

    def span(self, start: int, end: int, role: str = "mention") -> EvidenceSpan:
        text = self.text
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if not 0 <= start < end <= len(text):
            raise ValueError(f"Empty or invalid local span {start}:{end}")
        p, spans = self.passage, self.ingested.source_spans
        a, b = spans[p.normalized_start + start][0], spans[p.normalized_start + end - 1][1]
        raw = self.ingested.document.original_text[a:b]
        return EvidenceSpan(
            patient_id=p.patient_id, document_id=p.document_id, source_id=p.source_id,
            source_sha256=p.source_sha256, passage_id=p.passage_id, original_start=a, original_end=b,
            raw_text=raw, display_text=re.sub(r"\s+", " ", text[start:end]).strip(), role=role,
        )

    def whole(self) -> EvidenceSpan:
        return self.span(0, len(self.text))


def views(ingested: IngestedDocument) -> list[PassageView]:
    return [PassageView(p, ingested) for p in ingested.passages]
