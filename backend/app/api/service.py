"""End-to-end task flow: request -> plan (L4) -> retrieval/synthesis (L5) -> verification (L6) -> response."""
from __future__ import annotations

import os
import time
import uuid

from sqlalchemy import select

from backend.app.api.schemas import ConflictOut, Provenance, TaskResponse
from backend.app.layer3_store.models import ExtractionRunRow
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer4_planner.planner import plan_task
from backend.app.layer5_retrieval.engine import Executor, Synthesizer, build_timeline
from backend.app.layer6_verification.contradictions import detect_conflicts
from backend.app.layer6_verification.verify import ClaimVerifier, summarize


class UnknownPatient(KeyError):
    pass


def patient_conflicts(store: ClinicalStore, patient_id: str, as_of: str | None = None):
    return detect_conflicts(store.facts(patient_id, as_of=as_of))


def run_task(store: ClinicalStore, patient_id: str, request: str, llm=None,
             retrieval: str | None = None) -> TaskResponse:
    t0 = time.perf_counter()
    docs = store.documents(patient_id)
    if not docs:
        raise UnknownPatient(patient_id)
    # PLANNER=heuristic keeps the validated rule planner (with its require-term and ATC safety filters) even when an
    # LLM is configured; the LLM stays available for /api/verify (judge=groq) and extraction.
    plan = plan_task(request, llm if os.environ.get("PLANNER", "llm").lower() == "llm" else None)
    t1 = time.perf_counter()
    latest = max(d.document_date for d in docs if d.document_date)
    as_of = plan.as_of or latest
    ex = Executor(store, patient_id, as_of, retrieval=retrieval)
    sections, missing = ex.run(plan)
    t2 = time.perf_counter()
    conflicts = detect_conflicts(ex.all_facts)
    verifier = ClaimVerifier(store, patient_id, as_of, conflicts)
    claims = [c for s in sections for c in s.claims]
    for c in claims:
        verifier.verify(c)
    reviews = {r["item_key"]: r["status"] for r in store.review_items(patient_id)}
    for c in claims:
        c.review_status = reviews.get(c.claim_id)
    shown = {f for c in claims for f in c.fact_ids}
    concepts = {s.concept for s in plan.steps} | {f for s in plan.steps for f in s.filters.observation_names}
    syn: Synthesizer = ex.syn
    facts_by_id = {f.fact_id: f for f in ex.all_facts}
    conf_out = []
    for c in conflicts:
        cit = syn.citations([facts_by_id[i] for i in c.fact_ids if i in facts_by_id])
        for x in cit:
            x.verified = verifier.verify_citation(x)
        relevant = bool(set(c.fact_ids) & shown) or bool(set(c.concepts) & concepts)
        conf_out.append(ConflictOut(conflict_id=c.conflict_id, kind=c.kind, title=c.title, explanation=c.explanation,
                                    severity=c.severity, relevant_to_task=relevant, citations=cit,
                                    review_status=reviews.get(c.conflict_id)))
    conf_out.sort(key=lambda c: (not c.relevant_to_task, {"high": 0, "medium": 1, "low": 2}.get(c.severity, 3)))
    timeline = build_timeline(store, patient_id, as_of, syn)
    t3 = time.perf_counter()
    with store.Session() as s:
        run = s.scalars(select(ExtractionRunRow).order_by(ExtractionRunRow.started_at.desc())).first()
        components = run.payload.get("components", []) if run else []
    prov = Provenance(planner=plan.planner.name, planner_model=plan.planner.model, llm_configured=llm is not None,
                      extraction_components=components, database=store.engine.dialect.name,
                      retrieval_mode=ex.retrieval, retrieval_used=sorted(ex.retrieval_used),
                      retrieval_warnings=ex.retrieval_warnings)
    return TaskResponse(request_id="req:" + uuid.uuid4().hex[:12], patient_id=patient_id, request=request, as_of=as_of,
                        plan=plan, sections=sections, missing=missing, conflicts=conf_out, timeline=timeline,
                        verification=summarize(claims), provenance=prov,
                        timings_ms={"plan": round((t1 - t0) * 1000, 1), "retrieve": round((t2 - t1) * 1000, 1),
                                    "verify": round((t3 - t2) * 1000, 1), "total": round((t3 - t0) * 1000, 1)})


def verify_text(store: ClinicalStore, req, llm=None):
    """Phase 3: VeriFact-style verification of free text against one patient's record (see claim_verification)."""
    from backend.app.api.schemas import AtomicClaimOut, EvidenceOut, VerifyTextResponse
    from backend.app.layer6_verification.claim_verification import ClaimVerificationPipeline
    from backend.app.layer6_verification.verify import ClaimVerifier
    docs = store.documents(req.patient_id)
    if not docs:
        raise UnknownPatient(req.patient_id)
    as_of = req.as_of or max(d.document_date for d in docs if d.document_date)
    ex = Executor(store, req.patient_id, as_of, retrieval=req.retrieval_mode)
    pipe = ClaimVerificationPipeline(ex, ClaimVerifier(store, req.patient_id, as_of, []), req.judge, llm)
    results, timings = pipe.run(req.text, req.atomizer)
    claims = [AtomicClaimOut(text=r.claim.text, start=r.claim.start, end=r.claim.end, verdict=r.verdict,
                             needs_review=r.needs_review, review_reason=r.review_reason, deterministic=r.deterministic,
                             semantic=r.semantic,
                             evidence=[EvidenceOut(citation=c, entailment=e, contradiction=x, checks=d)
                                       for c, e, x, d in r.evidence]) for r in results]
    summary = {v: sum(c.verdict == v for c in claims) for v in ("supported", "contradicted", "not_addressed")}
    summary["needs_review"] = sum(c.needs_review for c in claims)
    return VerifyTextResponse(patient_id=req.patient_id, as_of=as_of, judge_requested=req.judge,
                              judge_used=pipe.judge_used, judge_model=pipe.judge_model, atomizer=req.atomizer,
                              retrieval_used=sorted(ex.retrieval_used), warnings=pipe.warnings + ex.retrieval_warnings,
                              summary=summary, claims=claims, timings_ms=timings)
