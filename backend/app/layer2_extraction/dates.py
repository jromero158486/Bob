"""German clinical date parsing with explicit precision and validity.

Malformed dates (e.g. '15/04/20156') are returned with valid=False rather than
silently corrected, so later layers can surface them as documentation issues.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS = {"jänner": 1, "januar": 1, "februar": 2, "feber": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
          "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))

_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 12.06.2015, 12.06.201511:02 (time glued to the year), 15/04/20156 (malformed year)
    ("dmy", re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{4}(?=\d{1,2}:\d{2})|\d{4,5}(?!\d))")),
    ("d_month_y", re.compile(rf"(?<!\d)(\d{{1,2}})\.\s*({_MONTH_RE})\s+(\d{{4}})\b", re.I)),
    ("month_y", re.compile(rf"\b(?:(Anfang|Mitte|Ende)\s+)?({_MONTH_RE})\s+(\d{{4}})\b", re.I)),
    ("my", re.compile(r"(?<![\d./])(\d{1,2})/(\d{4})(?![\d/])")),
]
_RELATIVE = re.compile(r"\b(?:in|nach)\s+(\d{1,2}|einem|einer|zwei|drei|sechs)\s+(Tag(?:en)?|Woche[n]?|Monat(?:en)?|Jahr(?:en)?)\b", re.I)
_WORDNUM = {"einem": 1, "einer": 1, "zwei": 2, "drei": 3, "sechs": 6}


@dataclass(frozen=True)
class DateMention:
    start: int
    end: int
    text: str
    value: str | None
    precision: str
    valid: bool


def _iso(y: int, m: int, d: int | None) -> str | None:
    try:
        date(y, m, d or 1)
    except ValueError:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}" if d else f"{y:04d}-{m:02d}"


def find_dates(text: str) -> list[DateMention]:
    found: list[DateMention] = []
    taken: list[tuple[int, int]] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            if kind == "dmy":
                d, mo, y = int(m[1]), int(m[2]), m[3]
                value = _iso(int(y), mo, d) if len(y) == 4 else None
                found.append(DateMention(m.start(), m.end(), m[0], value, "day", value is not None))
            elif kind == "d_month_y":
                value = _iso(int(m[3]), MONTHS[m[2].casefold()], int(m[1]))
                found.append(DateMention(m.start(), m.end(), m[0], value, "day", value is not None))
            elif kind == "month_y":
                value = _iso(int(m[3]), MONTHS[m[2].casefold()], None)
                found.append(DateMention(m.start(), m.end(), m[0], value, "month", value is not None))
            else:
                mo, y = int(m[1]), int(m[2])
                value = _iso(y, mo, None) if 1 <= mo <= 12 else None
                found.append(DateMention(m.start(), m.end(), m[0], value, "month", value is not None))
            taken.append((m.start(), m.end()))
    return sorted(found, key=lambda x: x.start)


def relative_due(text: str, anchor_iso: str | None) -> tuple[str, str, int, int] | None:
    """'in 2 Monaten' relative to the document date -> (YYYY-MM[-DD], precision, start, end)."""
    m = _RELATIVE.search(text)
    if not m or not anchor_iso or len(anchor_iso) < 10:
        return None
    n = int(m[1]) if m[1].isdigit() else _WORDNUM[m[1].casefold()]
    unit = m[2].casefold()
    y, mo, d = int(anchor_iso[:4]), int(anchor_iso[5:7]), int(anchor_iso[8:10])
    if unit.startswith("monat") or unit.startswith("jahr"):
        months = n if unit.startswith("monat") else 12 * n
        total = (y * 12 + mo - 1) + months
        return f"{total // 12:04d}-{total % 12 + 1:02d}", "month", m.start(), m.end()
    from datetime import timedelta
    days = n if unit.startswith("tag") else 7 * n
    due = date(y, mo, d) + timedelta(days=days)
    return due.isoformat(), "day", m.start(), m.end()
