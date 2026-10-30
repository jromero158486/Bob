"""Phase 2 retrieval ablation: lexical vs BGE-M3 dense vs hybrid (RRF) vs hybrid + BGE reranker.

    python -m evaluation.research.phase2_retrieval --database-url postgresql+psycopg://... \\
        --cases <ibm>/cases/expected.json [--extra-queries private.jsonl]

Queries are the benchmark questions themselves (English, over German documents) passed through the production
planner's term extraction; relevance is document-level (expected source document ids), so a passage counts as
relevant when it comes from a gold source document. expected.json is used for scoring only.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from pathlib import Path

from backend.app.layer3_store.db import make_engine
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer4_planner.contracts import PlanStep
from backend.app.layer4_planner.planner import _search_terms
from backend.app.layer5_retrieval.engine import Executor

MODES = ("lexical", "dense", "hybrid", "hybrid_rerank")


def _step(question: str) -> PlanStep:
    return PlanStep.model_validate({"step_id": "q", "title": question, "concept": "evaluation",
                                    "operation": "search_text", "filters": {"search_terms": _search_terms(question)}})


def score(ranked_docs: list[str], gold: set[str], k: int) -> dict:
    rels = [d in gold for d in ranked_docs[:k]]
    first = next((i for i, r in enumerate(ranked_docs) if r in gold), None)
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels))
    return {f"doc_recall@{k}": len(set(ranked_docs[:k]) & gold) / len(gold),
            "mrr": 0.0 if first is None else 1 / (first + 1),
            f"ndcg@{k}": dcg / sum(1 / math.log2(i + 2) for i in range(k)),
            f"precision@{k}": sum(rels) / k}


def run(store: ClinicalStore, patient_id: str, queries: list[dict], k: int) -> dict:
    as_of = max(d.document_date for d in store.documents(patient_id) if d.document_date)
    out = {}
    for mode in MODES:
        ex = Executor(store, patient_id, as_of, retrieval=mode)
        ex.search_passages(_step("warm-up query"), k)  # model loading is not counted as query latency
        rows = []
        for q in queries:
            t = time.perf_counter()
            top, passages, used = ex.search_passages(_step(q["question"]), k)
            ms = (time.perf_counter() - t) * 1000
            docs = [ex.syn.docs[passages[i].source_id].document_id for i in top]
            rows.append({"id": q["id"], "lang": q.get("lang", "en"), "used": used, "ms": round(ms, 1),
                         "returned": len(top), **score(docs, set(q["sources"]), k)})
        keys = [k_ for k_ in rows[0] if k_.startswith(("doc_recall", "mrr", "ndcg", "precision"))]
        agg = {key: round(sum(r[key] for r in rows) / len(rows), 3) for key in keys}
        lat = sorted(r["ms"] for r in rows)
        agg |= {"median_ms": lat[len(lat) // 2], "max_ms": lat[-1], "empty_results": sum(r["returned"] == 0 for r in rows),
                "modes_used": sorted({r["used"] for r in rows}), "backends": sorted(ex.retrieval_used),
                "warnings": sorted(set(ex.retrieval_warnings))}
        by_lang = {}
        for lang in sorted({r["lang"] for r in rows}):
            sub = [r for r in rows if r["lang"] == lang]
            by_lang[lang] = {key: round(sum(r[key] for r in sub) / len(sub), 3) for key in keys} | {"n": len(sub)}
        out[mode] = {"aggregate": agg, "by_language": by_lang, "per_query": rows}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--patient-id", default="patient-0000-0001")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--extra-queries", default="", help="Private JSONL: id, question, sources, lang")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default="artifacts/research/phase2_retrieval.json")
    a = ap.parse_args()
    queries = [{"id": c["id"], "question": c["question"], "sources": c["sources"], "lang": "en"}
               for c in json.loads(Path(a.cases).read_text())]
    if a.extra_queries:
        queries += [json.loads(line) for line in Path(a.extra_queries).read_text().splitlines() if line.strip()]
    store = ClinicalStore(make_engine(a.database_url))
    from backend.app.layer5_retrieval.embeddings import shared_encoder, shared_reranker
    enc, rr = shared_encoder(), shared_reranker()
    res = {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "embedding_model": f"{enc.name}@{enc.revision}", "reranker": f"{rr.name}@{rr.revision}",
           "pgvector": store.has_pgvector(), "k": a.k, "queries": len(queries),
           "relevance": "document-level (gold source document ids)", "modes": run(store, a.patient_id, queries, a.k)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print({k: v for k, v in res.items() if k != "modes"})
    for mode, r in res["modes"].items():
        print(mode, r["aggregate"], r["by_language"])


if __name__ == "__main__":
    main()
