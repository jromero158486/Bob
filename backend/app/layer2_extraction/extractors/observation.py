"""Observation/measurement extraction: vitals, echo, labs, tumour markers, staging."""
from __future__ import annotations

import re

from backend.app.layer2_extraction import terminology
from backend.app.layer2_extraction.contracts import Coding, ObservationDetails
from backend.app.layer2_extraction.extractors.base import Candidate, local_laterality
from backend.app.layer2_extraction.passage_view import PassageView

LOINC = "http://loinc.org"
_NUMBER = r"(\d+(?:[.,]\d+)?)"
_SEP = r"\s*(?::|=|\(|\bvon\b|\bbei\b)?\s*"


def _f(x: str | None) -> float | None:
    return float(x.replace(",", ".")) if x else None


def _obs(view, start, end, name, name_text, value_text, *, v=None, v2=None, unit=None, qualifier=None,
         loinc=None, display=None, value_span=None, laterality=None) -> Candidate:
    codings = (Coding(system=LOINC, code=loinc, display=display or name, mapping_source=terminology.observations()["version"]),) if loinc else ()
    det = ObservationDetails(name=name, name_text=name_text, value_text=value_text, value_num=v, value_num2=v2,
                             unit=unit, qualifier=qualifier, laterality=laterality)
    return Candidate(view, start, end, "observation", f"{name_text}: {value_text}", det, codings,
                     value_spans=[value_span] if value_span else [])


def _lexicon(view: PassageView) -> list[Candidate]:
    text, out = view.text, []
    for e in terminology.observations()["entries"]:
        names = "|".join(e["names"])
        if e["name"] == "heart_rate":
            val = r"(\d{2,3})(?:\s*-\s*(\d{2,3}))?(?:\s*\((\d{2,3})\))?\s*/\s*min"
        elif e["name"] == "mmse":
            val = r"(\d{1,2})\s*/\s*30"
        else:
            val = _NUMBER + r"\s*(%|cm|kg|°C|mm|kg/m2|kg/m²)?"
        rx = re.compile(rf"(?<![\wÄÖÜäöü-])(?P<n>{names})(?![\wÄÖÜäöü]){_SEP}(?P<v>{val})", re.I if e["name"] not in ("lvef", "heart_rate") else 0)
        for m in rx.finditer(text):
            g = m.groups()
            if e["name"] == "heart_rate":
                lo, hi, mean = m.group(3), m.group(4), m.group(5)
                v = _f(mean or lo)
                qual = "range (mean)" if hi else None
            else:
                v = _f(m.group(3))
                qual = None
            unit = e["unit"]
            out.append(_obs(view, m.start(), m.end(), e["name"], m["n"], m["v"].strip(), v=v, unit=unit,
                            qualifier=qual, loinc=e.get("loinc"), display=e["display"], value_span=m.span("v")))
    return out


_BP_VALUE = re.compile(r"(?<![\d/.])(\d{2,3})\s*/\s*(\d{2,3})(?![\d/.])(\s*mm\s?Hg)?")
_BP_QUAL = [("24", "24h mean"), ("Tagesmittel", "daytime mean"), ("Nachtmittel", "night-time mean"),
            ("Spitzen", "peak"), ("Aufnahme", "at admission"), ("Entgleisung", "hypertensive episode")]


def _blood_pressure(view: PassageView) -> list[Candidate]:
    text, cfg = view.text, terminology.observations()["blood_pressure"]
    name_rx = re.compile("|".join(map(re.escape, cfg["names"])))
    out = []
    for m in _BP_VALUE.finditer(text):
        sys_, dia = int(m[1]), int(m[2])
        if not (60 <= sys_ <= 300 and 30 <= dia <= 200 and sys_ > dia):
            continue
        before = text[max(0, m.start() - 60):m.start()]
        if re.search(r"MMSE", before[-12:]):
            continue
        names = list(name_rx.finditer(before))
        title = view.passage.section_title or ""
        name_text = names[-1][0] if names else (name_rx.search(title)[0] if name_rx.search(title) else None)
        if name_text is None and not m[3]:
            continue
        ctx = (name_text or "") + " " + before[-25:]
        qual = next((q for k, q in _BP_QUAL if k in ctx), None)
        if qual is None and re.search(r"\bAufnahme\b", text):
            qual = "at admission"
        if qual is None and re.search(r"\bbis\s*$", before):
            qual = "peak"
        out.append(Candidate(view, m.start(), m.end(), "observation", f"{name_text or 'RR'}: {m[0].strip()}",
                             ObservationDetails(name="blood_pressure", name_text=name_text or "RR", value_text=m[0].strip(),
                                                value_num=float(sys_), value_num2=float(dia), unit="mmHg", qualifier=qual),
                             (Coding(system=LOINC, code=cfg["loinc_panel"], display="Blood pressure panel",
                                     mapping_source=terminology.observations()["version"]),),
                             value_spans=[m.span()]))
    return out


_TNM = re.compile(r"\b((?:y|p|c|r){0,2}T(?:[0-4][a-d]?|is|x))\s+(N(?:[0-3][a-c]?|x))\s+(M(?:[01]|x))(?:\s+(V[0-2x]))?(?:\s+(G[1-4x]))?\b")
_BIRADS = re.compile(r"BI-?RADS\s*:?\s*(VI|V|IV|III|II|I|[0-6])\b", re.I)
_ALLRED = re.compile(r"Allred-?Score\s*:?\s*(\d)", re.I)
_STENOSIS = [
    re.compile(r"(\d{1,3})\s*%(?:ige)?\s+(?:[\wäöüÄÖÜ.-]+\s+){0,3}?[\wäöüÄÖÜ-]*[Ss]tenose"),
    re.compile(r"[Ss]klerose\s+\w+\.?\s*\((\d{1,3})\s*%\)"),
    re.compile(r"Einengung.{0,160}?zu\s+etwa\s+(\d{1,3})\s*%"),
]
_SIZE = re.compile(r"(?:maximale[rn]?\s+)?Ausdehnung\s+(?:des\s+Tumors\s+)?(?:von\s+)?(\d+(?:[.,]\d+)?(?:\s*x\s*\d+(?:[.,]\d+)?)?)\s*cm", re.I)


def _special(view: PassageView) -> list[Candidate]:
    text, out = view.text, []
    for r in terminology.observations()["receptors"]:
        rx = re.compile(rf"(?P<n>{'|'.join(r['names'])})\s*:?\s*(?P<v>positiv|negativ)(?:\s*\((?P<p>\d{{1,3}})\s*%)?", re.I)
        for m in rx.finditer(text):
            vt = m["v"] + (f" ({m['p']}%)" if m["p"] else "")
            out.append(_obs(view, m.start(), m.end(), r["name"], m["n"], vt, v=_f(m["p"]), unit="%" if m["p"] else None,
                            display=r["display"], value_span=(m.start("v"), m.end())))
    for m in _ALLRED.finditer(text):
        prev = [n for n in re.finditer(r"Östrogenrezeptor|Progesteronrezeptor", text[:m.start()])]
        out.append(_obs(view, m.start(), m.end(), "allred_score", "Allred-Score", m[1], v=float(m[1]),
                        qualifier=prev[-1][0] if prev else None, value_span=m.span(1)))
    for m in _TNM.finditer(text):
        out.append(_obs(view, m.start(), m.end(), "tnm_classification", "TNM", m[0], value_span=m.span()))
    for m in _BIRADS.finditer(text):
        out.append(_obs(view, m.start(), m.end(), "birads", "BI-RADS", m[1], value_span=m.span(1)))
    for rx in _STENOSIS:
        for m in rx.finditer(text):
            out.append(_obs(view, m.start(), m.end(), "stenosis_degree", m[0], f"{m[1]}%", v=float(m[1]), unit="%",
                            value_span=m.span(1), laterality=local_laterality(text, m.start(), m.end())))
    for m in _SIZE.finditer(text):
        out.append(_obs(view, m.start(), m.end(), "lesion_size", "Ausdehnung", f"{m[1]} cm", unit="cm",
                        v=_f(m[1].split("x")[0].strip()), value_span=m.span(1)))
    return out


_GENERIC = re.compile(r"(?P<n>[A-Za-zÄÖÜäöü][\wÄÖÜäöü .-]{0,30}?)\s*:\s*(?P<v>\d+(?:[.,]\d+)?)\s*(?P<u>mm|cm|%|kg|mmHg|/min|m/s|mg/dl|g/dl|mmol/l)?(?!\d|[.,/]\d|:)")
_GENERIC_SKIP = re.compile(r"ID|Fall|datum|Beginn|Ende|Tel|Zahl", re.I)


def _generic(view: PassageView, covered: list[tuple[int, int]]) -> list[Candidate]:
    if view.passage.passage_type != "observation_row":
        return []
    out = []
    for m in _GENERIC.finditer(view.text):
        if _GENERIC_SKIP.search(m["n"]) or re.search(r"\d", m["n"]) or any(a < m.end() and m.start() < b for a, b in covered):
            continue
        out.append(_obs(view, m.start(), m.end(), "uncoded", m["n"].strip(), (m["v"] + (" " + m["u"] if m["u"] else "")),
                        v=_f(m["v"]), unit=m["u"], value_span=m.span("v")))
    return out


def extract(view: PassageView) -> list[Candidate]:
    if view.passage.passage_type in ("table_header",):
        return []
    found = _lexicon(view) + _blood_pressure(view) + _special(view)
    # Prefer the longest candidate when two observation patterns cover the same value.
    found.sort(key=lambda c: -(c.end - c.start))
    kept: list[Candidate] = []
    for c in found:
        if not any(c.start < k.end and k.start < c.end and c.details.name == k.details.name for k in kept):
            kept.append(c)
    kept += _generic(view, [(c.start, c.end) for c in kept])
    return sorted(kept, key=lambda c: c.start)
