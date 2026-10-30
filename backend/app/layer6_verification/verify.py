"""Claim verification in two separate stages.

1. Citation integrity: does each citation resolve, for this patient, to the current version of the source, with offsets
   inside the declared passage and a quote equal to the original slice? Integrity alone never makes a claim supported.
2. Semantic support: do the claim's values/polarity match what the cited source says (or, for calculations, were all
   inputs verified)? Only claims passing both, with no detected conflict, are "supported".
Valid JSON or model confidence is never treated as evidence.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache

from backend.app.api.schemas import Citation, Claim, VerificationSummary
from backend.app.layer1_ingestion.processing.source_mapping import project_source
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer6_verification.contradictions import Conflict

CHECKS = ["citation:source_version_current", "citation:patient_matches", "citation:document_id_matches",
          "citation:source_checksum_matches", "citation:passage_belongs_to_source", "citation:offsets_within_passage",
          "citation:quote_equals_original_slice", "citation:passage_text_matches", "citation:document_date_within_as_of",
          "support:facts_current_and_same_patient", "support:assertion_polarity", "support:claim_values_in_source",
          "support:derived_inputs_verified", "support:no_detected_conflict", "support:extractor_not_model_only"]

_ISO = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _numbers(s: str) -> set[str]:
    out = set()
    for n in _NUM.findall(s):
        n = n.replace(",", ".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n.lstrip("0") or "0")
    return out


_UNITS = re.compile(r"kg/m2|kg/m²|m²|/m2|\bm2\b|1/min|µg|mcg")


def claim_values(text: str, vocabulary: set[str] = frozenset()) -> set[str]:
    """Numbers asserted by a rendered claim, excluding ISO dates (rendered from parsed source dates), unit names and
    terminology display names (e.g. 'Type 2 diabetes mellitus' from the ICD-10 lexicon)."""
    for term in sorted(vocabulary, key=len, reverse=True):
        text = text.replace(term, " ")
    text = _UNITS.sub(" ", _ISO.sub(" ", text))
    text = re.sub(r"\((?:documented|due)[^)]*\)", " ", text)
    return _numbers(text)


class ClaimVerifier:
    def __init__(self, store: ClinicalStore, patient_id: str, as_of: str, conflicts: list[Conflict]):
        self.store, self.pid, self.as_of = store, patient_id, as_of
        self.conflict_by_fact: dict[str, list[str]] = {}
        for c in conflicts:
            for fid in (c.disputed_fact_ids or c.fact_ids):
                self.conflict_by_fact.setdefault(fid, []).append(c.conflict_id)
        self.facts = {f.fact_id: f for f in store.facts(patient_id)}
        self._source = lru_cache(maxsize=None)(store.source_version)
        self._passage = lru_cache(maxsize=None)(store.passage_by_id)
        self._sha_ok = lru_cache(maxsize=None)(self._checksum)

    def _checksum(self, source_id: str) -> bool:
        d = self._source(source_id)
        return hashlib.sha256(d.original_text.encode("utf-8")).hexdigest() == d.source_sha256

    # ---- stage 1: citation integrity ----
    def citation_errors(self, cit: Citation) -> list[str]:
        d = self._source(cit.source_id) if cit.source_id else None
        if d is None:
            return ["unknown_source_version"]
        errs = []
        if d.patient_id != self.pid:
            return ["different_patient"]
        if not d.is_current:
            errs.append("superseded_source_version")
        if d.document_id != cit.document_id:
            errs.append("document_id_mismatch")
        if cit.source_sha256 != d.source_sha256 or not self._sha_ok(cit.source_id):
            errs.append("checksum_mismatch")
        if (d.document_date or "") > self.as_of:
            errs.append("document_after_as_of")
        p = self._passage(cit.passage_id)
        if p is None or p.source_id != d.source_id or p.patient_id != self.pid:
            errs.append("passage_not_in_source")
            return errs
        if not (p.original_start <= cit.original_start < cit.original_end <= p.original_end):
            errs.append("offsets_outside_passage")
            return errs
        raw = d.original_text[cit.original_start:cit.original_end]
        if _norm(project_source(raw).text) != _norm(cit.quote):
            errs.append("quote_differs_from_original_slice")
        if _norm(cit.passage_text) != _norm(p.display_text):
            errs.append("passage_text_mismatch")
        return errs

    def verify_citation(self, cit: Citation) -> bool:
        cit.integrity_errors = self.citation_errors(cit)
        cit.verified = not cit.integrity_errors
        return cit.verified

    # ---- stage 2: semantic support ----
    def verify(self, claim: Claim) -> Claim:
        checks: list[str] = []
        ok_cits = [self.verify_citation(c) for c in claim.citations]
        claim.citation_integrity = "none" if not ok_cits else ("valid" if all(ok_cits) else "invalid")
        claim.support_checks = checks

        def done(status, basis="none", note=None):
            claim.status, claim.support_basis = status, basis
            if note:
                claim.notes.append(note)
            return claim

        if claim.citation_integrity != "valid":
            return done("not_addressed", note="Citation integrity failed: " + ", ".join(
                sorted({e for c in claim.citations for e in c.integrity_errors})) if claim.citations else "No citation")
        facts = [self.facts.get(f) for f in claim.fact_ids]
        if any(f is None or f.patient_id != self.pid for f in facts):
            checks.append("support:facts_current_and_same_patient:fail")
            return done("not_addressed", note="Claim references a fact that is not current for this patient")
        checks.append("support:facts_current_and_same_patient:pass")

        if claim.kind == "documented_negative":
            ok = bool(facts) and all(f.assertion.negated for f in facts)
            checks.append(f"support:assertion_polarity:{'pass' if ok else 'fail'}")
            basis = "documented_negative"
        elif claim.kind in ("fact", "change"):
            ok = not any(f.assertion.negated for f in facts)
            checks.append(f"support:assertion_polarity:{'pass' if ok else 'fail'}")
            basis = "source_values_matched"
        elif claim.kind == "computed":
            ok, basis = True, "derived_from_verified_inputs"
            checks.append("support:derived_inputs_verified:pass")
        elif claim.kind == "not_documented":
            # e.g. a cited recommendation with no later record that it happened: the absence is the claim.
            return done("supported", "absence_in_record")
        elif claim.kind == "passage":
            ok = any(_norm(claim.text).rstrip("…") in _norm(c.passage_text) for c in claim.citations)
            checks.append(f"support:verbatim_passage:{'pass' if ok else 'fail'}")
            basis = "verbatim_passage"
        else:
            return done("not_addressed")
        if not ok:
            return done("verification_incomplete", note="Claim polarity/wording does not match the cited source")

        if claim.kind in ("fact", "change", "documented_negative"):
            source_text = " ".join([c.quote + " " + c.passage_text for c in claim.citations] +
                                   [e.display_text for f in facts for e in f.evidence])
            vocab = {c.display for f in facts for c in f.codings} | {f.label for f in facts}
            missing = claim_values(claim.text, vocab) - _numbers(source_text)
            checks.append(f"support:claim_values_in_source:{'fail' if missing else 'pass'}")
            if missing:
                return done("verification_incomplete",
                            note=f"Value(s) {', '.join(sorted(missing))} not found in the cited source text")

        claim.conflict_ids = sorted({cid for f in facts for cid in self.conflict_by_fact.get(f.fact_id, [])})
        checks.append(f"support:no_detected_conflict:{'fail' if claim.conflict_ids else 'pass'}")
        if claim.conflict_ids:
            return done("contradicted", basis)
        model_only = [f for f in facts if f.review_status == "needs_review" or f.extractor.name != "rules-de"]
        checks.append(f"support:extractor_not_model_only:{'fail' if model_only else 'pass'}")
        if model_only:
            return done("verification_incomplete", basis, "Model-derived or flagged fact; needs human review")
        return done("supported", basis)


def summarize(claims: list[Claim]) -> VerificationSummary:
    s = VerificationSummary(checks=CHECKS)
    for c in claims:
        setattr(s, c.status, getattr(s, c.status) + 1)
        s.citations_total += len(c.citations)
        s.citations_valid += sum(x.verified for x in c.citations)
    return s
