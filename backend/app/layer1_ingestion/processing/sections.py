"""Clinical section detection: medSpaCy Sectionizer when installed, safe rule fallback.

German rules are explicit and versionable. Unknown colon headings are retained.
"""
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

RULE_FILE = Path(__file__).resolve().parents[1] / "rules" / "german_sections.json"
_GENERIC_HEADING = re.compile(r"^[^:;.!?]{3,75}:\s*$")
# Dates inside a heading ("Schädel-CT (11.06.2015):") must not disqualify it.
_DATE_IN_HEADING = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")


def _canonical(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).strip().strip(": ").casefold().split())


@lru_cache(maxsize=1)
def german_headings() -> dict[str, str]:
    items = json.loads(RULE_FILE.read_text(encoding="utf-8"))
    return {_canonical(name): category for category, names in items.items() for name in names}


@lru_cache(maxsize=1)
def _medspacy_pipe():
    """Return configured genuine medSpaCy pipe, or None if not installed.

    We deliberately do not install a fake shim named medspacy.
    """
    try:
        import spacy
        from medspacy.section_detection import SectionRule
    except ImportError:
        return None
    nlp = spacy.blank("de")
    component = nlp.add_pipe("medspacy_sectionizer", config={
        "rules": None, "language_code": "de", "span_attrs": None,
        "require_start_line": True,
    })
    rules = [SectionRule(name + suffix, category) for category, names in
             json.loads(RULE_FILE.read_text(encoding="utf-8")).items()
             for name in names for suffix in (":", "")]
    component.add(rules)
    return nlp


def detect_sections(text: str, engine: str = "auto") -> tuple[dict[tuple[int, int], str], str]:
    """Return mappings from exact [start,end) heading substrings to categories.

    Only whole-line headings are accepted; an inline 'Befund: ...' is not a heading.
    """
    if engine not in {"auto", "medspacy", "rules"}:
        raise ValueError(f"Unknown section engine: {engine}")
    normalized = german_headings()
    found: dict[tuple[int, int], str] = {}
    for m in re.finditer(r"[^\n]+", text):
        s = m.group(0)
        trimmed = s.strip()
        if not trimmed:
            continue
        category = normalized.get(_canonical(trimmed))
        if category is None and _GENERIC_HEADING.fullmatch(_DATE_IN_HEADING.sub("D", trimmed)):
            category = "unclassified"
        if category is not None:
            lead = len(s) - len(s.lstrip())
            found[(m.start() + lead, m.start() + lead + len(trimmed))] = category

    nlp = _medspacy_pipe() if engine != "rules" else None
    if engine == "medspacy" and nlp is None:
        raise RuntimeError("medSpaCy is unavailable: install pip install '.[clinical]'")
    if nlp is None:
        return found, "rules"

    # The paper-derived real sectionizer is run over the normalized document;
    # anchored deterministic matches remain the source of safe boundaries.
    doc = nlp(text)
    for sec in doc._.sections:
        # medSpaCy >=1.0 exposes token offsets (title_start/title_end), not a Span.
        if sec.title_start >= sec.title_end or not sec.category:
            continue
        span = doc[sec.title_start:sec.title_end]
        line_start = text.rfind("\n", 0, span.start_char) + 1
        line_end = text.find("\n", span.end_char)
        line_end = len(text) if line_end == -1 else line_end
        line = text[line_start:line_end]
        if _canonical(line) != _canonical(span.text):
            continue  # inline mention, not a whole-line heading
        lead = len(line) - len(line.lstrip())
        found[(line_start + lead, line_start + lead + len(line.strip()))] = str(sec.category)
    return found, "medspacy"
