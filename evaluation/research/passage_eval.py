"""Passage-level retrieval and answer-completeness evaluation on a manually reviewed answer-span set.

    python -m evaluation.research.passage_eval --database-url postgresql+psycopg://... \\
        --cases <ibm>/cases/expected.json --gold private_passage_gold.json [--extra-queries private_de.jsonl]

The gold file (private, never committed: it quotes source wording) lists per question the atomic answer facts and,
for each, a regex over passage text whose matches were reviewed by hand; a fact may be restricted to documents
(e.g. only the current medication list). Gold passages are resolved over the patient's indexed passages.

Metrics (k = 6, the number of passages the production search step returns, and 10):
  fact_recall@k     share of answer facts with at least one supporting passage in the top k
  passage_recall@k  share of all gold passages in the top k (duplicates across letters count separately)
  mrr, ndcg@k       first / graded position of gold passages (binary relevance)
  e2e completeness  share of answer facts whose regex matches the cited source text of a claim in the full
                    run_task() response (heuristic planner), and of a claim whose status is "supported"
These questions and facts were never used for fusion tuning (evaluation/research/fusion_tuning.py).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
from pathlib import Path

from backend.app.api.service import run_task
from backend.app.layer3_store.db import make_engine
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer5_retrieval.embeddings import configured_model
from backend.app.layer5_retrieval.engine import RANKINGS, Executor
from evaluation.research.phase2_retrieval import _step

MODES = ("lexical", "dense", "hybrid_equal", "hybrid", "hybrid_rerank")
KS = (6, 10)


def resolve_gold(store: ClinicalStore, patient_id: str, gold: list[dict]) -> dict[str, dict[str, set[str]]]:
    docs = {d.source_id: d.document_id for d in store.documents(patient_id)}
    ps = store.passages(patient_id, [r.passage_id for r in store.embedding_rows(patient_id, configured_model())])
    out = {}
    for q in gold:
        facts = {}
        for name, spec in q["facts"].items():
            rx, only = (spec, None) if isinstance(spec, str) else (spec["rx"], set(spec.get("docs", [])) or None)
            facts[name] = {pid for pid, p in ps.items() if p.source_id in docs
                           and (only is None or docs[p.source_id] in only) and re.search(rx, p.display_text, re.I | re.S)}
            if not facts[name]:
                raise SystemExit(f"gold fact {q['id']}/{name} matches no passage")
        out[q["id"]] = facts
    return out


def score(top: list[str], facts: dict[str, set[str]], k: int) -> dict:
    gold = set().union(*facts.values())
    rel = [i in gold for i in top[:k]]
    first = next((n for n, i in enumerate(top) if i in gold), None)
    ideal = sum(1 / math.log2(n + 2) for n in range(min(k, len(gold))))
    return {f"fact_recall@{k}": sum(bool(set(top[:k]) & s) for s in facts.values()) / len(facts),
            f"passage_recall@{k}": len(set(top[:k]) & gold) / len(gold),
            f"ndcg@{k}": sum(r / math.log2(n + 2) for n, r in enumerate(rel)) / ideal,
            **({"mrr": 0.0 if first is None else 1 / (first + 1)} if k == KS[0] else {})}


def _mean(rows: list[dict], keys) -> dict:
    return {key: round(sum(r[key] for r in rows) / len(rows), 3) for key in keys}


def retrieval(store, patient_id, queries, gold) -> dict:
    as_of = max(d.document_date for d in store.documents(patient_id) if d.document_date)
    out = {}
    for mode in MODES:
        ex = Executor(store, patient_id, as_of, retrieval="hybrid" if mode == "hybrid_equal" else mode)
        if mode == "hybrid_equal":
            ex.fusion_weights, ex.rrf_k = dict.fromkeys(RANKINGS, 1.0), 60
        ex.search_passages(_step("warm-up query"), 10)
        rows = []
        for q in queries:
            t = time.perf_counter()
            top, _, used = ex.search_passages(_step(q["question"]), max(KS))
            ms = (time.perf_counter() - t) * 1000
            row = {"id": q["id"], "lang": q["lang"], "used": used, "ms": round(ms, 1)}
            for k in KS:
                row |= score(top, gold[q["gold_id"]], k)
            rows.append(row)
        keys = [k for k in rows[0] if k not in ("id", "lang", "used", "ms")]
        lat = sorted(r["ms"] for r in rows)
        out[mode] = {"aggregate": _mean(rows, keys) | {"median_ms": lat[len(lat) // 2], "max_ms": lat[-1]},
                     "by_language": {lg: _mean([r for r in rows if r["lang"] == lg], keys) for lg in sorted({r["lang"] for r in rows})},
                     "warnings": sorted(set(ex.retrieval_warnings)), "per_query": rows}
    return out


def end_to_end(store, patient_id, queries, gold, regexes, modes=("lexical", "auto")) -> dict:
    out = {}
    for mode in modes:
        run_task(store, patient_id, "warm-up: allergies?", retrieval=mode)
        rows = []
        for q in queries:
            t = time.perf_counter()
            r = run_task(store, patient_id, q["question"], retrieval=mode)
            ms = (time.perf_counter() - t) * 1000
            claims = [c for s in r.sections for c in s.claims]
            cited = lambda cs: " \n ".join(ct.passage_text for c in cs for ct in c.citations)  # noqa: E731
            facts = regexes[q["gold_id"]]
            all_txt, sup_txt = cited(claims), cited([c for c in claims if c.status == "supported"])
            rows.append({"id": q["id"], "lang": q["lang"], "ms": round(ms), "retrieval_used": r.provenance.retrieval_used,
                         "completeness_cited": sum(bool(re.search(rx, all_txt, re.I | re.S)) for rx in facts.values()) / len(facts),
                         "completeness_supported": sum(bool(re.search(rx, sup_txt, re.I | re.S)) for rx in facts.values()) / len(facts),
                         "missing": [n for n, rx in facts.items() if not re.search(rx, all_txt, re.I | re.S)]})
        lat = sorted(r["ms"] for r in rows)
        out[mode] = {"aggregate": _mean(rows, ("completeness_cited", "completeness_supported"))
                     | {"median_ms": lat[len(lat) // 2], "max_ms": lat[-1]}, "per_query": rows}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--patient-id", default="patient-0000-0001")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--extra-queries", default="")
    ap.add_argument("--out", default="artifacts/research/passage_eval.json")
    a = ap.parse_args()
    gold_spec = json.loads(Path(a.gold).read_text())
    ids = {g["id"] for g in gold_spec}
    queries = [{"id": c["id"], "gold_id": c["id"], "question": c["question"], "lang": "en"}
               for c in json.loads(Path(a.cases).read_text()) if c["id"] in ids]
    if a.extra_queries:
        for line in filter(str.strip, Path(a.extra_queries).read_text().splitlines()):
            q = json.loads(line)
            gid = q["id"].rsplit("-", 1)[0]
            if gid in ids:
                queries.append({"id": q["id"], "gold_id": gid, "question": q["question"], "lang": q.get("lang", "de")})
    store = ClinicalStore(make_engine(a.database_url))
    gold = resolve_gold(store, a.patient_id, gold_spec)
    regexes = {g["id"]: {n: (s if isinstance(s, str) else s["rx"]) for n, s in g["facts"].items()} for g in gold_spec}
    res = {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "queries": len(queries), "questions": len(ids), "facts": sum(len(f) for f in gold.values()),
           "gold_passages": len(set().union(*(s for f in gold.values() for s in f.values()))),
           "relevance": "passage-level, manually reviewed answer spans",
           "retrieval": retrieval(store, a.patient_id, queries, gold),
           "end_to_end": end_to_end(store, a.patient_id, queries, gold, regexes)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print({k: v for k, v in res.items() if k not in ("retrieval", "end_to_end")})
    for mode, r in res["retrieval"].items():
        print("retrieval", mode, json.dumps(r["aggregate"]), json.dumps(r["by_language"]))
    for mode, r in res["end_to_end"].items():
        print("e2e", mode, json.dumps(r["aggregate"]))
        print("   missing:", {x["id"]: x["missing"] for x in r["per_query"] if x["missing"]})


if __name__ == "__main__":
    main()
