"""Reversible view of HTML-ish German source text.

Every normalized character carries the original Python string [start,end) span.
We never shift offsets by replacing BR tags or unescaping entities in-place.
"""
from dataclasses import dataclass
from html import unescape
import re

_TOKEN = re.compile(r"(?is)<[^>]*>|&(?:#[xX][0-9a-f]+|#[0-9]+|[a-z][a-z0-9]+);|\r\n|\r|\n")
_BREAK_TAG = re.compile(r"(?is)^<\s*(?:br\b|/\s*(?:p|div|tr|li|h[1-6])\b|(?:p|tr|li)\b)[^>]*>$")


@dataclass(frozen=True)
class TextProjection:
    text: str
    spans: tuple[tuple[int, int], ...]

    def original_bounds(self, start: int, end: int) -> tuple[int, int]:
        if not (0 <= start < end <= len(self.spans)):
            raise ValueError(f"Invalid normalized span: {start}:{end}")
        return self.spans[start][0], self.spans[end - 1][1]


def project_source(raw: str) -> TextProjection:
    display: list[str] = []
    spans: list[tuple[int, int]] = []

    def push(fragment: str, start: int, end: int, one_to_one: bool = False) -> None:
        for i, ch in enumerate(fragment):
            display.append(ch)
            spans.append((start + i, start + i + 1) if one_to_one else (start, end))

    previous = 0
    for m in _TOKEN.finditer(raw):
        if previous < m.start():
            push(raw[previous:m.start()], previous, m.start(), True)
        token = m.group(0)
        if token.startswith("<"):
            if _BREAK_TAG.match(token):
                push("\n", m.start(), m.end())
        elif token.startswith("&"):
            decoded = unescape(token)
            push(decoded, m.start(), m.end())
        else:
            push("\n", m.start(), m.end())
        previous = m.end()
    if previous < len(raw):
        push(raw[previous:], previous, len(raw), True)
    return TextProjection("".join(display), tuple(spans))
