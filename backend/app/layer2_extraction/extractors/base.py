"""Common candidate structure produced by all Layer 2 extractors."""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.layer2_extraction.contracts import Coding, Details, ExtractorInfo, FactType
from backend.app.layer2_extraction.passage_view import PassageView

RULES = ExtractorInfo(name="rules-de", version="0.1.0")


@dataclass
class Candidate:
    view: PassageView
    start: int
    end: int
    fact_type: FactType
    label: str
    details: Details
    codings: tuple[Coding, ...] = ()
    extractor: ExtractorInfo = RULES
    value_spans: list[tuple[int, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    needs_review: bool = False
    use_context: bool = True
    target: tuple[int, int] | None = None
    assertion_override: dict | None = None


def laterality(text: str):
    t = text.casefold()
    if any(k in t for k in ("beidseits", "bds.", "bilateral", "beidseitig")):
        return "bilateral"
    import re
    left = re.search(r"\b(?:li\.|links|linke[nrms]?|sin\.?|sinistra)(?![\wäöü])", t)
    right = re.search(r"\b(?:re\.|rechts|rechte[nrms]?|dext\.?|dextra)(?![\wäöü])", t)
    if left and right:
        return None
    return "left" if left else ("right" if right else None)


def local_laterality(text: str, start: int, end: int):
    """Laterality from the clause around [start,end) (bounded by , ; or sentence end)."""
    import re
    left = max([m.end() for m in re.finditer(r"[,;]|\.\s+(?=[A-ZÄÖÜ])", text[:start])], default=0)
    m = re.search(r"[,;]|\.\s+(?=[A-ZÄÖÜ])", text[end:])
    right = end + m.start() if m else len(text)
    return laterality(text[left:right])
