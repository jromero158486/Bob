"""Medication extraction: deterministic table-row parser + lexicon-anchored narrative parser."""
from __future__ import annotations

import re

from backend.app.layer2_extraction import terminology
from backend.app.layer2_extraction.contracts import Coding, DoseSchedule, MedicationDetails
from backend.app.layer2_extraction.extractors.base import Candidate
from backend.app.layer2_extraction.passage_view import PassageView

_STRENGTH = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(mg|mcg|µg|g|ml|IE|I\.E\.)$", re.I)
_NUM = re.compile(r"^\d+(?:[.,]\d+)?$")
_UNIT_ONLY = re.compile(r"^(mg|mcg|µg|g|ml|IE)$", re.I)
_ROUTE = re.compile(r"^(oral|p\.o\.?|s\.c\.?|i\.v\.?|i\.m\.?|subkutan|intravenös|inhalativ|rektal|transdermal|sublingual)$", re.I)
_FORM = re.compile(r"^(Tropfen|Injektionslösung|Tabl\.?|Tablette[n]?|Filmtablette[n]?|Kapsel[n]?|Spray|Pflaster|Lösung|Pen|Brausetablette[n]?)$", re.I)
_DOSE = re.compile(r"^(\d+(?:/\d+)?|½|¼)$")
_FREQ = re.compile(r"^\d+\s*x\s*/\s*(Woche|Tag|Monat)$|^(wöchentlich|täglich|monatlich)$", re.I)
_DOSE_UNIT = re.compile(r"^(ST|Stk\.?|Tropfen|Dosen|Dosis|Tabl\.?|Hub|Hübe|IE|Amp\.?)$", re.I)


def _num(s: str) -> float:
    if s in ("½",):
        return 0.5
    if s in ("¼",):
        return 0.25
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s.replace(",", "."))


def _coding(lex) -> tuple[Coding, ...]:
    if not lex:
        return ()
    e = lex.entry
    return (Coding(system="http://www.whocc.no/atc", code=e["atc"], display=e["ingredient"], mapping_source=lex.version),)


def parse_row(view: PassageView) -> Candidate | None:
    text = view.text
    toks = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", text)]
    if len(toks) < 2:
        return None
    name_end_idx = None
    strength = form = route = freq = dose_unit = None
    schedule: list[str] = []
    sched_span = None
    unparsed: list[str] = []
    value_spans = []
    i = 0
    while i < len(toks):
        a, b, t = toks[i]
        nxt = toks[i + 1][2] if i + 1 < len(toks) else ""
        if i > 0 and _STRENGTH.match(t):
            strength = _STRENGTH.match(t).groups()
            value_spans.append((a, b))
        elif i > 0 and _NUM.match(t) and _UNIT_ONLY.match(nxt) and strength is None:
            strength = (t, nxt)
            value_spans.append((a, toks[i + 1][1]))
            i += 1
        elif i > 0 and _ROUTE.match(t):
            route = t
        elif i > 0 and _FORM.match(t) and route is None and not schedule:
            form = t
        elif route is not None and _DOSE.match(t) and not schedule:
            j = i
            while j < len(toks) and _DOSE.match(toks[j][2]) and j - i < 4:
                j += 1
            if j - i >= 3:
                schedule = [x[2] for x in toks[i:j]]
                sched_span = (a, toks[j - 1][1])
                value_spans.append(sched_span)
                i = j - 1
            else:
                unparsed.append(t)
        elif _FREQ.match(t):
            freq = " ".join(x[2] for x in toks[i:])
            value_spans.append((a, toks[-1][1]))
            break
        elif i > 0 and _DOSE_UNIT.match(t) and (route is not None or strength is not None):
            dose_unit = t
        else:
            if name_end_idx is None and strength is None and form is None and route is None:
                i += 1
                continue
            unparsed.append(t)
        if name_end_idx is None:
            name_end_idx = i
        i += 1
    if name_end_idx is None or name_end_idx == 0 or (strength is None and route is None and not schedule):
        return None
    drug_text = text[toks[0][0]:toks[name_end_idx - 1][1]]
    lex = terminology.medication_by_name(drug_text)
    sched = None
    if schedule:
        vals = [_num(x) for x in schedule] + [None] * (4 - len(schedule))
        sched = DoseSchedule(morning=vals[0], noon=vals[1], evening=vals[2], night=vals[3], text=text[sched_span[0]:sched_span[1]])
    details = MedicationDetails(
        drug_text=drug_text, ingredient=lex.entry["ingredient"] if lex else None,
        strength_value=_num(strength[0]) if strength else None, strength_unit=strength[1] if strength else None,
        form=form, route=route, schedule=sched, frequency_text=freq, dose_unit=dose_unit,
        statement="medication_list", unparsed=tuple(unparsed),
    )
    return Candidate(view, 0, len(text), "medication", text.strip(), details, _coding(lex), value_spans=value_spans,
                     notes=["schedule columns assumed mo-mi-ab-na (morning, noon, evening, night)"] if sched else [])


_N_STRENGTH = re.compile(r"\s*(\d+(?:[.,]\d+)?)\s*(mg|mcg|µg|g|ml|IE)\b", re.I)
_N_SCHED = re.compile(r"(\d(?:/\d)?|½)\s*-\s*(\d(?:/\d)?|½)\s*-\s*(\d(?:/\d)?|½)(?:\s*-\s*(\d(?:/\d)?|½))?")
_N_TIME = re.compile(r"\b(morgens|mittags|abends|nachts|zur\s+Nacht)\b", re.I)
_N_DOSE_BEFORE = re.compile(r"(\d+)\s+(Hübe[n]?|Hub|Tabl\.?|Tabletten|Tropfen|Kapseln)\s*$", re.I)
_STARTED = re.compile(r"\bbegonnen\b|\beingeleitet\b|\bneu\s+angesetzt\b|\bangesetzt\b", re.I)
_CHANGED = re.compile(r"\bAnpassung\b|\bumgestellt\b|\berhöht\b|\breduziert\b|\bgesteigert\b|\bgeändert\b", re.I)
_ADMIN = re.compile(r"\bverabreicht\b|\bVerabreichung\b|\bappliziert\b|\bHübe[n]?\b", re.I)


def parse_narrative(view: PassageView) -> list[Candidate]:
    text = view.text
    out = []
    statement = ("changed" if _CHANGED.search(text) else "started" if _STARTED.search(text)
                 else "administered" if _ADMIN.search(text) else "mentioned")
    for lex in terminology.medications(text):
        a, b = lex.start, lex.end
        value_spans = []
        strength = None
        sched = None
        cursor = b
        m = _N_STRENGTH.match(text, b)
        if m:
            strength = (m[1], m[2])
            value_spans.append((m.start(1), m.end()))
            cursor = m.end()
        window = text[cursor:cursor + 30]
        ms = _N_SCHED.search(window)
        mt = _N_TIME.search(window)
        if ms:
            vals = [_num(x) if x else None for x in ms.groups()]
            sched = DoseSchedule(morning=vals[0], noon=vals[1], evening=vals[2], night=vals[3], text=ms[0])
            value_spans.append((cursor + ms.start(), cursor + ms.end()))
        elif mt:
            word = mt[1].casefold()
            slot = {"morgens": "morning", "mittags": "noon", "abends": "evening"}.get(word, "night")
            sched = DoseSchedule(**{slot: 1.0}, text=mt[1])
            value_spans.append((cursor + mt.start(), cursor + mt.end()))
        before = _N_DOSE_BEFORE.search(text[:a])
        freq = before[0] if before else None
        details = MedicationDetails(
            drug_text=text[a:b], ingredient=lex.entry["ingredient"],
            strength_value=_num(strength[0]) if strength else None, strength_unit=strength[1] if strength else None,
            schedule=sched, frequency_text=freq, statement=statement,
        )
        end = max([b] + [e for _, e in value_spans])
        out.append(Candidate(view, a, end, "medication", text[a:end], details, _coding(lex), value_spans=value_spans))
    return out


def extract(view: PassageView) -> list[Candidate]:
    if view.passage.passage_type == "medication_row":
        row = parse_row(view)
        return [row] if row else []
    if view.passage.passage_type in ("table_header", "section_heading"):
        return []
    return parse_narrative(view)
