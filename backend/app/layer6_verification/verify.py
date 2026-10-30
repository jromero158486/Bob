"""Claim-level verification (VeriFact/FactEHR-inspired, deterministic).

Statuses: supported, contradicted, not_addressed, verification_incomplete. Valid JSON or a model's
confidence is never treated as evidence; only source-resolvable citations are.
"""
from __future__ import annotations

import hashlib

from backend.app.api.schemas import Claim, VerificationSummary
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer6_verification.contradictions import Conflict

CHECKS = ["citation_resolves_to_original_offsets", "source_checksum_matches", "patient_matches",
          "document_date_within_as_of", "assertion_consistent_with_claim_kind", "conflict_cross_check",
          "model_only_or_review_flag"]


class ClaimVerifier:
    def __init__(self, store: ClinicalStore, patient_id: str, as_of: str, conflicts: list[Conflict]):
        self.store, self.pid, self.as_of = store, patient_id, as_of
        self.docs = {d.document_id: d for d in store.documents(patient_id)}
        self.conflict_by_fact: dict[str, list[str]] = {}
        for c in conflicts:
            for fid in (c.disputed_fact_ids or c.fact_ids):
                self.conflict_by_fact.setdefault(fid, []).append(c.conflict_id)
        self.facts = {f.fact_id: f for f in store.facts(patient_id)}

    def verify_citation(self, cit) -> bool:
        d = self.docs.get(cit.document_id)
        if d is None or d.patient_id != self.pid:
            return False
        if hashlib.sha256(d.original_text.encode("utf-8")).hexdigest() != d.source_sha256:
            return False
        raw = d.original_text[cit.original_start:cit.original_end]
        if not raw or not cit.passage_id.startswith(d.source_id):
            return False
        if (d.document_date or "") > self.as_of:
            return False
        return True

    def verify(self, claim: Claim) -> Claim:
        for c in claim.citations:
            c.verified = self.verify_citation(c)
        if not claim.citations or not all(c.verified for c in claim.citations):
            claim.status = "not_addressed"
            claim.notes.append("Citation could not be verified against the original source")
            return claim
        facts = [self.facts[f] for f in claim.fact_ids if f in self.facts]
        if len(facts) != len(claim.fact_ids):
            claim.status = "not_addressed"
            return claim
        if any(f.patient_id != self.pid for f in facts):
            claim.status = "not_addressed"
            return claim
        if claim.kind == "fact" and any(f.assertion.negated for f in facts):
            claim.status = "verification_incomplete"
            claim.notes.append("Claim polarity disagrees with a negated source statement")
            return claim
        claim.conflict_ids = sorted({cid for f in facts for cid in self.conflict_by_fact.get(f.fact_id, [])})
        if claim.conflict_ids:
            claim.status = "contradicted"
            return claim
        if any(f.review_status == "needs_review" or f.extractor.name != "rules-de" for f in facts):
            claim.status = "verification_incomplete"
            claim.notes.append("Model-derived or flagged fact; needs human review")
            return claim
        claim.status = "supported"
        return claim


def summarize(claims: list[Claim]) -> VerificationSummary:
    s = VerificationSummary(checks=CHECKS)
    for c in claims:
        setattr(s, c.status, getattr(s, c.status) + 1)
    return s
