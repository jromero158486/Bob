"""German NegEx/ConText-inspired assertion classification.

Two engines share one versioned rule file (resources/context_rules_de.json):
- 'native': a small deterministic implementation of the ConText scope algorithm
  (Harkema et al., 2009; Chapman et al. NegEx, 2001) adapted to German triggers.
- 'medspacy': the published medSpaCy ConText component configured with the same
  German rules (only when medspacy is installed).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from backend.app.layer1_ingestion.processing.segmentation import _ABBREV
from backend.app.layer2_extraction.contracts import Assertion, ContextTrigger

RULES_PATH = Path(__file__).parent / "resources" / "context_rules_de.json"


@dataclass(frozen=True)
class _Rule:
    category: str
    direction: str
    regex: re.Pattern


@lru_cache(maxsize=1)
def _load():
    cfg = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules = tuple(_Rule(r["category"], r["direction"], re.compile(r["pattern"], re.I)) for r in cfg["rules"])
    return (cfg["version"], rules, re.compile(cfg["clause_terminators"], re.I),
            re.compile(cfg["sentence_terminators"]), re.compile(cfg["question_prefix"], re.I))


def rules_version() -> str:
    return _load()[0]


def _triggers(text: str):
    _, rules, *_ = _load()
    found: list[tuple[int, int, _Rule]] = []
    for rule in rules:
        for m in rule.regex.finditer(text):
            if m.end() == m.start():
                continue
            if any(a <= m.start() and m.end() <= b for a, b, _ in found):
                continue  # covered by a longer trigger, e.g. 'kein Anhalt für' over 'kein'
            found.append((m.start(), m.end(), rule))
    return sorted(found, key=lambda t: t[0])


def _scope(text: str, start: int, end: int, direction: str) -> tuple[int, int]:
    _, _, clause, sentence, _ = _load()
    term = sentence if direction == "BIDIRECTIONAL" else clause
    marks = [(m.start(), m.end()) for m in term.finditer(text)
             if not (text[m.start()] == "." and _ABBREV.search(text[:m.end()]))]
    left = max((b for a, b in marks if b <= start), default=0)
    right = min((a for a, b in marks if a >= end), default=len(text))
    if direction == "FORWARD":
        return end, right
    if direction == "BACKWARD":
        return left, start
    return left, right


def classify_native(text: str, targets: list[tuple[int, int]]) -> list[Assertion]:
    _, _, _, _, question = _load()
    is_question = bool(question.search(text))
    trig = _triggers(text)
    out = []
    for ts, te in targets:
        hits = []
        for a, b, rule in trig:
            if ts <= a and b <= te:
                continue  # trigger inside the target itself (e.g. 'kein' inside a quoted name)
            s, e = _scope(text, a, b, rule.direction)
            if s <= ts and te <= e:
                hits.append(ContextTrigger(category=rule.category, text=text[a:b], passage_offset=a))
        out.append(_assertion(hits, is_question, "native:" + rules_version()))
    return out


def _assertion(hits: list[ContextTrigger], is_question: bool, engine: str) -> Assertion:
    cats = {h.category for h in hits}
    return Assertion(
        negated="NEGATED_EXISTENCE" in cats,
        certainty="possible" if ("POSSIBLE_EXISTENCE" in cats or is_question) else "affirmed",
        temporality="historical" if "HISTORICAL" in cats else ("future" if "HYPOTHETICAL" in cats else "current"),
        experiencer="family" if "FAMILY" in cats else "patient",
        question=is_question, triggers=tuple(hits), engine=engine,
    )


@lru_cache(maxsize=1)
def _medspacy_nlp():
    try:
        import spacy
        from medspacy.context import ConText, ConTextRule  # noqa: F401 - availability check
    except ImportError:
        return None
    _, rules, clause, sentence, _ = _load()
    nlp = spacy.blank("de")
    ctx = nlp.add_pipe("medspacy_context", config={"rules": None})
    mrules = []
    for r in rules:
        mrules.append(ConTextRule(literal=r.regex.pattern, category=r.category, pattern=r.regex.pattern,
                                  direction=r.direction))
    ctx.add(mrules)
    return nlp


def classify_medspacy(text: str, targets: list[tuple[int, int]]) -> list[Assertion]:
    """Run medSpaCy ConText; clause terminators are enforced by splitting into spaCy sentences."""
    nlp = _medspacy_nlp()
    if nlp is None:
        raise RuntimeError("medSpaCy is not installed")
    from spacy.tokens import Span
    _, _, clause, sentence, question = _load()
    is_question = bool(question.search(text))
    doc = nlp.make_doc(text)
    ents = []
    for ts, te in targets:
        sp = doc.char_span(ts, te, label="TARGET", alignment_mode="expand")
        ents.append(sp)
    # medSpaCy ConText scopes are bounded by sentences; use sentence terminators as boundaries.
    cuts = {m.end() for m in sentence.finditer(text)}
    for tok in doc:
        tok.is_sent_start = tok.i == 0 or any(doc[tok.i - 1].idx + len(doc[tok.i - 1]) <= c <= tok.idx for c in cuts)
    unique = []
    for sp in ents:
        if sp is not None and not any(sp.start < u.end and u.start < sp.end for u in unique):
            unique.append(sp)
    doc.ents = [Span(doc, s.start, s.end, label="TARGET") for s in unique]
    for name, proc in nlp.pipeline:
        doc = proc(doc)
    out = []
    for (ts, te), sp in zip(targets, ents):
        hits = []
        ent = next((e for e in doc.ents if sp is not None and e.start == sp.start and e.end == sp.end), None)
        if ent is not None:
            for mod in ent._.modifiers:
                trig_span = doc[mod.modifier_span[0]:mod.modifier_span[1]]
                a, b = trig_span.start_char, trig_span.end_char
                if a < te and ts < b:
                    continue
                # Apply the same clause boundary for FORWARD/BACKWARD as the native engine.
                if mod.direction in ("FORWARD", "BACKWARD"):
                    s, e = _scope(text, a, b, mod.direction)
                    if not (s <= ts and te <= e):
                        continue
                hits.append(ContextTrigger(category=mod.category, text=text[a:b], passage_offset=a))
        out.append(_assertion(hits, is_question, "medspacy-context:" + rules_version()))
    return out


def classify(text: str, targets: list[tuple[int, int]], engine: str = "native") -> list[Assertion]:
    """'native' is the default: medSpaCy's regex matcher drops triggers that do not align with
    spaCy's German tokenisation of abbreviations such as 'Vd.a.', 'St.p.' or 'Z.n.'
    (see tests/test_layer2_context.py)."""
    if not targets:
        return []
    if engine == "medspacy":
        return classify_medspacy(text, targets)
    if engine != "native":
        raise ValueError(f"Unknown context engine: {engine}")
    return classify_native(text, targets)
