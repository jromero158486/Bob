"""Conservative structure-aware segmentation; never infer medication semantics.

First preserve physical table rows; only split prose at safe sentence boundaries.
"""
from dataclasses import dataclass
import re
from backend.app.layer1_ingestion.processing.sections import detect_sections
from backend.app.layer1_ingestion.processing.source_mapping import TextProjection

_MED_ROUTE = re.compile(r"\b(?:oral|p\.o\.|i\.v\.|s\.c\.|subkutan|intravenös|inhalativ|rektal)\b", re.I)
_MED_TIMING = re.compile(r"\b(?:\d(?:/\d+)?\s+){2,}\d(?:/\d+)?\b|\b\d+x\s*/\s*woche\b", re.I)
_TABLE_HEADER = re.compile(r"\bapplikation\b.*\bmo\b.*\bmi\b|\bparameter\b.*\b(?:einheit|referenzbereich)\b", re.I)
_VALUE_ROW = re.compile(r"^[\wÄÖÜäöüß() /.-]{2,48}:\s*[-+]?\d[\d.,/]*\s*(?:mmHg|kg|cm|°C|%|mm|/min|mg|g|mmol/l|U/l)?\b", re.I)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])")
_ABBREV = re.compile(r"(?:\bDr|\bProf|\bPat|\bZ\.n|\bSt\.p|\bbzw|\bca|\bmax|\bmin|\bli|\bre|\bu\.a)\.$", re.I)


@dataclass(frozen=True)
class SegmentedSpan:
    start: int
    end: int
    passage_type: str
    section: str | None
    section_title: str | None


def _physical_lines(text: str):
    pos = 0
    for line in text.splitlines(keepends=True):
        value = line.rstrip("\r\n")
        left = len(value) - len(value.lstrip())
        right = len(value.rstrip())
        if left < right:
            yield pos + left, pos + right, value[left:right]
        else:
            yield None, None, ""
        pos += len(line)
    if not text or not text.endswith("\n"):
        return


def _split_sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    part = text[start:end]
    cut_points = [0]
    for m in _SENTENCE_BREAK.finditer(part):
        if not _ABBREV.search(part[:m.start()]):
            cut_points.append(m.end())
    cut_points.append(len(part))
    result = []
    for a, b in zip(cut_points, cut_points[1:]):
        while a < b and part[a].isspace():
            a += 1
        while b > a and part[b-1].isspace():
            b -= 1
        if a < b:
            result.append((start + a, start + b))
    return result


def segment(projection: TextProjection, engine: str = "auto") -> tuple[list[SegmentedSpan], str]:
    text = projection.text
    headings, used_engine = detect_sections(text, engine)
    current_section = None
    current_title = None
    spans: list[SegmentedSpan] = []
    for start, end, line in _physical_lines(text):
        if start is None:
            continue
        if (start, end) in headings:
            current_section = headings[(start, end)]
            current_title = line
            spans.append(SegmentedSpan(start, end, "section_heading", current_section, current_title))
            continue
        if _TABLE_HEADER.search(line) or line.casefold().strip() == "parameter":
            kind = "table_header"
        elif current_section in {"discharge_medication", "admission_medication", "medication"} and (
            _MED_ROUTE.search(line) or _MED_TIMING.search(line)
        ):
            kind = "medication_row"
        elif _MED_ROUTE.search(line) and _MED_TIMING.search(line) and len(line) < 150:
            kind = "medication_row"
        elif _VALUE_ROW.search(line):
            kind = "observation_row"
        else:
            kind = "sentence"
        # Physically wrapped prose: merge only lowercase continuations. Any
        # table/heading boundary remains untouched. Internal BRs stay in raw_text.
        if (kind == "sentence" and spans and spans[-1].passage_type == "sentence"
                and spans[-1].section == current_section
                and line[0].islower()
                and not re.search(r"[.!?:]\s*$", text[spans[-1].start:spans[-1].end])
                and "\n\n" not in text[spans[-1].end:start]):
            p = spans.pop()
            for a, b in _split_sentences(text, p.start, end):
                spans.append(SegmentedSpan(a, b, "sentence", current_section, current_title))
        elif kind == "sentence":
            for a, b in _split_sentences(text, start, end):
                spans.append(SegmentedSpan(a, b, "sentence", current_section, current_title))
        else:
            spans.append(SegmentedSpan(start, end, kind, current_section, current_title))
    return spans, used_engine
