"""Isolated adapter for GERNERMED++ (Frei, Frei-Stuber & Kramer, J Biomed Inform 2023).

The published models require spaCy 3.2.x, which conflicts with the main app's spaCy 3.7
(medSpaCy). The model therefore runs in a separate interpreter configured by:
  GERNERMED_PYTHON  path to a Python with spaCy 3.2.3 + the model wheel installed
  GERNERMED_MODEL   model package name or path (default de_GERNERMEDpp_GottBERT)
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

WORKER = Path(__file__).with_name("gernermed_worker.py")


@dataclass(frozen=True)
class NerEntity:
    label: str
    start: int
    end: int
    text: str


class NerUnavailable(RuntimeError):
    pass


class GernermedNER:
    name = "gernermed++"

    def __init__(self, python: str, model: str = "de_GERNERMEDpp_GottBERT", timeout: int = 600):
        self.python, self.model, self.timeout = python, model, timeout
        self.meta: dict = {}

    @classmethod
    def from_env(cls) -> "GernermedNER | None":
        py = os.environ.get("GERNERMED_PYTHON")
        if not py:
            return None
        return cls(py, os.environ.get("GERNERMED_MODEL", "de_GERNERMEDpp_GottBERT"))

    @property
    def version(self) -> str:
        if not self.meta:
            return f"{self.model} (not run)"
        return f"{self.meta.get('model')}=={self.meta.get('model_version')} (spaCy {self.meta.get('spacy_version')})"

    def annotate(self, texts: list[str]) -> list[list[NerEntity]]:
        if not Path(self.python).exists():
            raise NerUnavailable(f"GERNERMED_PYTHON not found: {self.python}")
        proc = subprocess.run([self.python, str(WORKER)], input=json.dumps({"model": self.model, "texts": texts}),
                              capture_output=True, text=True, timeout=self.timeout)
        if proc.returncode != 0:
            raise NerUnavailable(f"GERNERMED++ worker failed: {proc.stderr.strip().splitlines()[-1:]}")
        out = json.loads(proc.stdout)
        self.meta = {k: v for k, v in out.items() if k != "results"}
        if len(out["results"]) != len(texts):
            raise NerUnavailable("GERNERMED++ returned a mismatched number of results")
        return [[NerEntity(**e) for e in ents] for ents in out["results"]]


ATTRIBUTE_LABELS = ("Strength", "Dosage", "Frequency", "Duration", "Form", "Route")


def associate_attributes(ents: list[NerEntity], max_gap: int = 40) -> list[dict]:
    """Attach GERNERMED++ attribute entities to a Drug entity in the same passage.

    German medication text puts attributes after the drug ("Ramipril 5 mg 1-0-0 p.o."), so each attribute goes to
    the nearest preceding Drug within `max_gap` characters, else to the nearest following Drug within `max_gap`.
    Returns [{"drug", "start", "end", "attrs": {label: [texts]}}] in passage order."""
    drugs = sorted((e for e in ents if e.label == "Drug"), key=lambda e: e.start)
    groups = [{"drug": d.text, "start": d.start, "end": d.end, "attrs": {}} for d in drugs]
    for e in sorted((e for e in ents if e.label in ATTRIBUTE_LABELS), key=lambda e: e.start):
        before = [g for g in groups if g["end"] <= e.start and e.start - g["end"] <= max_gap]
        after = [g for g in groups if g["start"] >= e.end and g["start"] - e.end <= max_gap]
        g = before[-1] if before else (after[0] if after else None)
        if g is not None:
            g["attrs"].setdefault(e.label, []).append(e.text)
    return groups
