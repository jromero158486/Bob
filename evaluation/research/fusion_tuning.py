"""Fusion diagnosis and weight tuning for hybrid retrieval, on VALIDATION queries only.

    python -m evaluation.research.fusion_tuning --database-url postgresql+psycopg://... --queries private.json

Validation queries are the private generalisation tasks (request + gold source document ids), which are disjoint
from the 28 Phase 2 evaluation queries and the passage-level evaluation set. Each component ranking (lexical,
BGE-M3 dense/sparse/multi-vector) is computed once per query, then weighted RRF is evaluated over a grid.
Relevance is document-level, as in phase2_retrieval.
"""
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
from pathlib import Path

from backend.app.layer3_store.db import make_engine
from backend.app.layer3_store.repository import ClinicalStore
from backend.app.layer5_retrieval.engine import RANKINGS, Executor
from evaluation.research.phase2_retrieval import _step, score

GRID = (0.0, 0.25, 0.5, 1.0)


def fuse(rankings: dict[str, list[str]], weights: dict[str, float], k_rrf: int = 60) -> list[str]:
    sc: dict[str, float] = {}
    for name, ranking in rankings.items():
        w = weights.get(name, 0.0)
        for rank, pid in enumerate(ranking if w else []):
            sc[pid] = sc.get(pid, 0) + w / (k_rrf + rank)
    return sorted(sc, key=lambda i: -sc[i])


def evaluate(rows: list[dict], weights: dict[str, float], k: int, k_rrf: int = 60) -> dict:
    per = [score([r["doc_of"][i] for i in fuse(r["rankings"], weights, k_rrf)], r["gold"], k) for r in rows]
    return {key: round(sum(p[key] for p in per) / len(per), 3) for key in per[0]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--queries", required=True, help="Private JSON list of {patient_id, request, sources}")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default="artifacts/research/fusion_tuning.json")
    a = ap.parse_args()
    store = ClinicalStore(make_engine(a.database_url))
    qs = [q for q in json.loads(Path(a.queries).read_text()) if q.get("sources")]
    rows, ex_by_pid = [], {}
    for q in qs:
        pid = q["patient_id"]
        if pid not in ex_by_pid:
            as_of = max(d.document_date for d in store.documents(pid) if d.document_date)
            ex_by_pid[pid] = Executor(store, pid, as_of, retrieval="hybrid")
        ex = ex_by_pid[pid]
        _, passages, used = ex.search_passages(_step(q["request"]), 50)
        assert used == "hybrid", ex.retrieval_warnings
        rows.append({"request": q["request"], "gold": set(q["sources"]), "rankings": dict(ex.last_rankings),
                     "doc_of": {i: ex.syn.docs[p.source_id].document_id for i, p in passages.items()}})
    single = {name: evaluate(rows, {name: 1.0}, a.k) | {"empty": sum(not r["rankings"].get(name) for r in rows)}
              for name in RANKINGS}
    grid = []
    for wl, ws, wc in itertools.product(GRID, GRID, GRID):
        w = {"dense": 1.0, "lexical": wl, "sparse": ws, "colbert": wc}
        for k_rrf in (10, 60):
            grid.append({"weights": w, "rrf_k": k_rrf, **evaluate(rows, w, a.k, k_rrf)})
    ndcg, rec = f"ndcg@{a.k}", f"doc_recall@{a.k}"
    grid.sort(key=lambda g: (-g[ndcg], -g["mrr"], -g[rec], sum(g["weights"].values())))
    res = {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
           "validation_queries": len(rows), "relevance": "document-level", "k": a.k,
           "single_rankings": single, "equal_rrf": evaluate(rows, dict.fromkeys(RANKINGS, 1.0), a.k),
           "dense_only": evaluate(rows, {"dense": 1.0}, a.k), "best": grid[0], "top10": grid[:10]}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False))
    for key in ("single_rankings", "equal_rrf", "dense_only", "best"):
        print(key, json.dumps(res[key]))
    for g in grid[:6]:
        print(g)


if __name__ == "__main__":
    main()
