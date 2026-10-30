"""Phase 3 claim-verification evaluation: deterministic baseline vs deterministic + semantic judge.

    python -m evaluation.research.phase3_verification --database-url postgresql+psycopg://... \\
        --claims private_claims.json [--judges none,nli,nli_only,groq] [--retrieval auto]

Claims: author-written synthetic German (and a few English) statements about the synthetic IBM patient, labelled
supported / contradicted / not_addressed against the source documents before running any judge (private file:
they paraphrase source content). Each claim is verified on its own (no atomization) with per-claim evidence
retrieval (k=5). "nli_only" is an ablation: NLI verdict on the same evidence without the deterministic veto.

Metrics: 3-class accuracy; false-support rate = P(pred supported | gold not supported); contradiction recall =
P(pred contradicted | gold contradicted); support recall; review (abstention) rate; median latency per claim.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

from backend.app.layer2_extraction.llm.provider import provider_from_env
from backend.app.layer3_store.db import make_engine
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer5_retrieval.engine import Executor
from backend.app.layer6_verification.claim_verification import (CONTRA_T, ENTAIL_T, AtomicClaim,
                                                                 ClaimVerificationPipeline)
from backend.app.layer6_verification.verify import ClaimVerifier

LABELS = ("supported", "contradicted", "not_addressed")


def nli_only(r) -> str:
    if not r.evidence or r.evidence[0][1] is None:
        return "not_addressed"
    ent, con = max(e for _, e, _, _ in r.evidence), max(x for _, _, x, _ in r.evidence)
    if ent >= ENTAIL_T and con < CONTRA_T:
        return "supported"
    if con >= CONTRA_T and ent < ENTAIL_T:
        return "contradicted"
    return "not_addressed"


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    neg = [r for r in rows if r["gold"] != "supported"]
    con = [r for r in rows if r["gold"] == "contradicted"]
    sup = [r for r in rows if r["gold"] == "supported"]
    lat = sorted(r["ms"] for r in rows)
    return {"n": n, "accuracy": round(sum(r["pred"] == r["gold"] for r in rows) / n, 3),
            "false_support_rate": round(sum(r["pred"] == "supported" for r in neg) / len(neg), 3),
            "contradiction_recall": round(sum(r["pred"] == "contradicted" for r in con) / len(con), 3),
            "support_recall": round(sum(r["pred"] == "supported" for r in sup) / len(sup), 3),
            "review_rate": round(sum(r["review"] for r in rows) / n, 3),
            "confusion": {g: dict(Counter(r["pred"] for r in rows if r["gold"] == g)) for g in LABELS},
            "median_ms": round(lat[n // 2]), "max_ms": round(lat[-1])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--patient-id", default="patient-0000-0001")
    ap.add_argument("--claims", required=True)
    ap.add_argument("--judges", default="none,nli,nli_only")
    ap.add_argument("--retrieval", default="auto")
    ap.add_argument("--out", default="artifacts/research/phase3_verification.json")
    a = ap.parse_args()
    store = ClinicalStore(make_engine(a.database_url))
    claims = json.loads(Path(a.claims).read_text())
    as_of = max(d.document_date for d in store.documents(a.patient_id) if d.document_date)
    res = {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "claims": len(claims), "labels": dict(Counter(c["label"] for c in claims)), "retrieval": a.retrieval,
           "thresholds": {"entail": ENTAIL_T, "contradiction": CONTRA_T}, "configs": {}}
    for judge in a.judges.split(","):
        llm = provider_from_env() if judge == "groq" else None
        ex = Executor(store, a.patient_id, as_of, retrieval=a.retrieval)
        pipe = ClaimVerificationPipeline(ex, ClaimVerifier(store, a.patient_id, as_of, []),
                                         "nli" if judge == "nli_only" else judge, llm)
        pipe.verify_claim(AtomicClaim("Warm-up Aussage 1 mg"))
        rows = []
        for c in claims:
            t = time.perf_counter()
            r = pipe.verify_claim(AtomicClaim(c["text"]))
            ms = (time.perf_counter() - t) * 1000
            pred = nli_only(r) if judge == "nli_only" else r.verdict
            rows.append({"text": c["text"], "cat": c["cat"], "gold": c["label"], "pred": pred,
                         "review": pred != "supported" if judge == "nli_only" else r.needs_review,
                         "reason": r.review_reason, "ms": ms, "semantic": r.semantic})
        res["configs"][judge] = {"judge_used": pipe.judge_used, "judge_model": pipe.judge_model,
                                 "retrieval_used": sorted(ex.retrieval_used), "warnings": sorted(set(pipe.warnings))[:5],
                                 "metrics": metrics(rows),
                                 "errors": [{k: r[k] for k in ("text", "gold", "pred", "reason")} for r in rows if r["pred"] != r["gold"]],
                                 "per_claim": rows}
        print(judge, pipe.judge_used, pipe.judge_model, json.dumps(res["configs"][judge]["metrics"]))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
