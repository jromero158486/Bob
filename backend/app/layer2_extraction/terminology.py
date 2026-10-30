"""Local, versioned terminology lexicons (candidate codes only; see resources/*.json)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RESOURCES = Path(__file__).parent / "resources"


def _load(name: str) -> dict:
    return json.loads((RESOURCES / name).read_text(encoding="utf-8"))


def resource_checksums() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in sorted(RESOURCES.glob("*.json"))}


@dataclass(frozen=True)
class LexMatch:
    start: int
    end: int
    entry: dict
    version: str


def _longest_non_overlapping(matches: list[LexMatch]) -> list[LexMatch]:
    chosen: list[LexMatch] = []
    for m in sorted(matches, key=lambda x: (-(x.end - x.start), x.start)):
        if not any(m.start < c.end and c.start < m.end for c in chosen):
            chosen.append(m)
    return sorted(chosen, key=lambda x: x.start)


@lru_cache(maxsize=None)
def _compiled(name: str, key: str):
    data = _load(name)
    out = []
    for e in data["entries"]:
        pats = e.get(key) or []
        if key == "names":  # literal names; allow flexible whitespace/hyphen
            rx = [r"(?<![\wÄÖÜäöüß-])" + r"[\s-]?".join(map(re.escape, re.split(r"[\s-]+", n))) + r"(?![\wÄÖÜäöüß])"
                  for n in sorted(pats, key=len, reverse=True)]
        else:
            rx = pats
        out.append((e, [re.compile(r, re.I if key != "names" else 0) for r in rx]))
    return data["version"], out


def match(name: str, text: str, key: str = "patterns") -> list[LexMatch]:
    version, entries = _compiled(name, key)
    found = [LexMatch(m.start(), m.end(), e, version) for e, rxs in entries for rx in rxs for m in rx.finditer(text)]
    return _longest_non_overlapping(found)


def medications(text: str) -> list[LexMatch]:
    return match("medications_de.json", text, "names")


def medication_by_name(name: str) -> LexMatch | None:
    hits = medications(name)
    return hits[0] if hits else None


def diagnoses(text: str) -> list[LexMatch]:
    return match("diagnoses_de.json", text)


def procedures(text: str) -> list[LexMatch]:
    return match("procedures_de.json", text)


def allergens(text: str) -> list[LexMatch]:
    return match("allergens_de.json", text)


@lru_cache(maxsize=1)
def observations() -> dict:
    return _load("observations_de.json")
