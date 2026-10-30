# Experiments

Every result records: commit, model versions, data split, configuration, execution status, metrics.
Generated outputs go to `artifacts/research/` (gitignored). Scripts live in `evaluation/research/`.

## §0 Baseline (commit 87c4089)
- Tests: 66 passed, 2 skipped (`.venv/bin/python -m pytest -q`).
- Data: IBM patient-0000-0001 (8 docs; tuning data, not held out) + 10 author-written tasks (private file).
- Config A (heuristic planner, rules-de + native ConText + medSpaCy sections + GERNERMED++):
  IBM 15 key terms 57/61, exact values in supported claims 27/28; new tasks 23/23; all citations integrity-valid;
  median 0.5 s per task.
- Config B (Groq `openai/gpt-oss-120b` planner + LLM extraction): new tasks 22/23 values; IBM situation 2 shows
  ~20 review-only (LLM) claims per question; median 12.7 s.
- Details and caveats: `docs/RELIABILITY_PASS.md`.

## §1a German ConText/NegEx (`python -m evaluation.research.phase1_context`)
Data: `evaluation/research/data/context_de.jsonl`, 40 author-written synthetic sentences (14 negated, 7 possible,
8 historical/future, 5 family). Written before looking at the engine output; not clinician-annotated.
Rules `de-context-0.1`, commit of the run is stored in `artifacts/research/phase1_context.json`.

| engine | negation P/R/F1 | possible R | temporality R | family R | all 4 attributes correct | time (40 sents) |
|---|---|---|---|---|---|---|
| native (default) — before rule changes | 1.00 / 0.79 / 0.88 | 0.57 | 1.00 | 0.80 | 33/40 | 3 ms |
| medSpaCy ConText, same rules — before | 1.00 / 0.79 / 0.88 | 0.43 | 0.63 | 0.80 | 29/40 | 936 ms |
| native, rules `de-context-0.2` (tuned on this set — not held out) | 1.00 / 1.00 / 1.00 | 1.00 | 1.00 | 1.00 | 40/40 | 1 ms |
| medSpaCy, `de-context-0.2` (same set) | 1.00 / 1.00 / 1.00 | 0.86 | 0.63 | 1.00 | 36/40 | 647 ms |

**Held-out set** `context_de_heldout.jsonl` (30 sentences written after the 0.2 rule change, rules not adjusted
afterwards; 10 negated, 6 possible, 6 temporal, 4 family):

| engine (`de-context-0.2`) | negation P/R/F1 | possible P/R | temporality P/R | family P/R | all correct |
|---|---|---|---|---|---|
| native | 1.00 / 0.80 / 0.89 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 0.75 | 27/30 |
| medSpaCy ConText | 1.00 / 0.80 / 0.89 | 1.00 / 0.83 | 1.00 / 0.83 | 1.00 / 0.75 | 25/30 |

Held-out errors: "nicht auskultierbar", "fehlen" (post-posed negation verbs not in rules), "Großmutter" (relative
not in the family list). These are left unfixed so the held-out numbers stay honest.

Failure analysis (both engines): post-posed negation ("wurde nicht beobachtet/festgestellt"), verb negation
("verneint"), hedges ("am ehesten", "möglicherweise", "nicht auszuschließen"), negated family history. medSpaCy
additionally misses `Z.n.`, `St.p.`, `Vd.a.` (spaCy's German tokenizer splits the abbreviations, so its token-aligned
matcher drops them) — the reason the native engine is the default.

## §1b Extraction ablation (`python -m evaluation.research.phase1_extraction`, commit 5182ead)

IBM patient-0000-0001 (8 German documents), medSpaCy sectioning, IBM extracted JSON as **silver** reference
(evaluation only). Document-level matching: (document, ATC) for medications, (document, ICD-10 3-char) for
affirmed diagnoses, (document, observation name) restricted to names the reference covers.

| config | facts | needs_review | grounded | med P/R/F1 | dx P/R/F1 | obs P/R/F1 | time |
|---|---|---|---|---|---|---|---|
| rules | 284 | 1 | 284/284 | 1.00/1.00/1.00 | 0.974/0.661/0.787 | 1.00/1.00/1.00 | 0.15 s |
| rules + GERNERMED++ | 285 (+1 model-only) | 2 | 285/285 | 1.00/1.00/1.00 | 0.974/0.661/0.787 | 1.00/1.00/1.00 | 14–17 s |
| rules + LLM (gpt-oss-120b) | 324–329 (+40–45 LLM) | 41–46 | all | 1.00/1.00/1.00 | 0.974/0.661/0.787 | 1.00/1.00/1.00 | 45–68 s |

LLM added diagnoses (+24), procedures (+6), recommendations (+5) and medications (+5) (run 1). None changed the
silver-standard scores: the 19 missed (document, ICD-3) pairs are mostly concepts negated in the source (I27, I31,
I49) or absent from the local lexicon (H34/H53/H54, D48, G93, E66, I50), and the lexicon-based candidate linker
(added in 5182ead) cannot code what the lexicon lacks.

GERNERMED++ attribute association (21 rule-extracted medications, nearest-Drug association within 40 chars):

| | rule has attribute | GERNERMED++ found | agrees |
|---|---|---|---|
| drug | 21 | 21 | — |
| strength | 17 | 17 | 17 |
| frequency / schedule | 20 | 7 | presence only |
| route | 16 | 0 | — (no Route entities emitted) |
| form | 4 | 4 | presence only |

Conclusion: on this patient GERNERMED++ confirms drugs and strengths but adds no correct new medication; it misses
most German table schedules ("1 0 1/2 0") and all routes. The deterministic parser stays primary.
Limits: one synthetic patient, silver reference, rules partly tuned on the same documents.

## §2 Retrieval ablation (`python -m evaluation.research.phase2_retrieval`, commit 90e8bae)

Store: PostgreSQL 16 + pgvector, IBM patient (354 passages, all indexed with BGE-M3 rev 5617a9f61b02 in
one ingest run). Queries: the 14 IBM benchmark questions that have a gold source (English, over German documents)
plus author-written German translations of the same 14 (private, outside the repo). Lexical terms come from the
production planner's `_search_terms`; the model query is `"<question>: <terms>"`. Relevance is
**document-level**: a passage counts as relevant if it comes from a gold source document. k = 10, CPU only, model
load excluded from latency.

| mode | doc-recall@10 | MRR | nDCG@10 | P@10 | empty results | median / max latency |
|---|---|---|---|---|---|---|
| lexical (baseline) | 0.280 | 0.233 | 0.109 | 0.093 | 18/28 | 3 / 14 ms |
| BGE-M3 dense (pgvector) | **0.982** | **0.882** | **0.632** | **0.593** | 0/28 | 298 / 466 ms |
| hybrid RRF (lexical + dense + sparse + ColBERT) | 0.875 | 0.801 | 0.573 | 0.543 | 0/28 | 318 / 541 ms |
| hybrid + bge-reranker-v2-m3 (top 20) | 0.899 | 0.801 | 0.612 | 0.579 | 0/28 | 4.7 / 8.9 s |

By language (dense): EN doc-recall 1.00 / MRR 0.87, DE 0.96 / 0.89. Lexical: EN 0.38 / 0.36, DE 0.18 / 0.11
(the planner's term extraction uses an English stop-word list, so German questions produce poor terms).

Findings: BGE-M3 dense retrieval removes the cross-language failure of lexical search (18 of 28 lexical queries
returned nothing). Unweighted RRF with the weaker lexical, sparse and ColBERT lists *lowers* quality against dense
alone; the reranker recovers part of it at ~15x latency. The production default stays `RETRIEVAL_MODE=lexical`
until hybrid weighting is tuned on data other than this test set; `dense` is the best configuration measured here.

Caveats: 8 documents and 1–3 gold documents per question make document-level recall easy to inflate (no
passage-level gold exists); one synthetic patient; German translations are author-written; this measures the
`search_text` step only, not structured-fact answers.

## §2b Phase 2 deployment, fusion tuning and passage-level evaluation (commits d83c54f…d20c9c7)

**Deployment (Docker Compose, private IBM data, CPU-only VM).** `db` = `pgvector/pgvector:pg16`, `models` = BGE-M3 +
bge-reranker-v2-m3 kept loaded in a separate service (`backend/Dockerfile.models`, weights in a persistent HF cache
volume), `backend` uses it through `EMBEDDING_SERVICE_URL`. The existing volume created by `postgres:16-alpine`
(musl) broke under the glibc image: text btree indexes were invalid, so the composite FK check on
`passage_embeddings` could not "see" existing passages (`ForeignKeyViolation`). Migration `0003` reindexes every table;
after it, the existing volume was kept and all 354 passages were embedded (`pgvector: true`), and a restart re-uses
them (`already_indexed: 354`). `REFRESH COLLATION VERSION` is not possible (musl records no version).

Warmed Docker API, unseen requests, `RETRIEVAL_MODE=auto`, Groq planner with `OPENAI_REASONING_EFFORT=low`
(wall time per `POST /api/tasks`, measured by the client):

| Request | retrieval_used | plan | retrieve | verify | total | citations valid |
|---|---|---|---|---|---|---|
| DE anaesthesia: bleeding risk / anticoagulation | dense:pgvector | 2.3 s | 0.5 s | 0.2 s | 3.0 s | 22/22 |
| EN physiotherapist: mobility, falls, deficits | dense:pgvector | 1.9 s | 1.2 s | 0.2 s | 3.3 s | 22/22 |
| EN brain imaging | dense:pgvector | 1.7 s | 0.5 s | 0.2 s | 2.4 s | 5/5 |
| DE mammography / breast biopsy findings | dense:pgvector | 1.7 s | 0.9 s | 0.2 s | 2.7 s | 22/22 |

Explicit modes on the same request: `lexical` 0.2 s retrieval, `dense` 0.9 s, `hybrid` 0.9 s, `hybrid_rerank` 8.0 s
(cross-encoder over the fused top 20 on CPU; above budget together with planning). Groq planner latency varied
between 1.6 s and 15 s across calls (default reasoning effort, rate-limit back-off); planning is now bounded by
`PLANNER_TIMEOUT` (10 s) and `PLANNER_RETRIES` (1) with a reported heuristic fallback. A first run without the
sign-off filter returned "befundet: Dr. Arzt vidiert: Dr. Arzt" as a top dense hit; sign-off-only passages are now
excluded from retrieval (they remain in the store and in citations of other passages' documents).
IBM benchmark with the heuristic planner on the pgvector DB: `auto` (dense) and `lexical` give identical answer
scores (57/61 key terms, 27/28 exact values; new tasks 23/23), median 1.3 s vs 0.5 s per task.

**Why equal-weight RRF hurt (validation queries only: the 10 private generalisation tasks, 9 with gold documents;
disjoint from the 28 evaluation queries and the passage set).** Document-level, k=10:

| Ranking alone | MRR | nDCG@10 | empty |
|---|---|---|---|
| lexical | 0.333 | 0.089 | 5/9 |
| BGE-M3 dense | 0.870 | 0.443 | 0 |
| BGE-M3 sparse | 0.676 | 0.378 | 0 |
| BGE-M3 multi-vector | 0.741 | 0.465 | 0 |
| equal RRF (k=60) | 0.528 | 0.373 | |
| selected: dense 1, lexical 1, sparse 0.5, colbert 0, k=10 | 0.815 | 0.481 | |

With RRF k=60 the reciprocal-rank curve is nearly flat over the top 10, so a passage ranked moderately by three
weaker rankings outscores dense's top hit; the weak lexical ranking (empty or off-topic for 5/9 queries) adds noise.
Weighted RRF (`HYBRID_WEIGHTS`, `RRF_K`) was grid-searched (`evaluation/research/fusion_tuning.py`; selection criterion
nDCG@10 then MRR, fixed before running). Nine queries is far too few for a reliable choice; `auto` stays dense.

**Passage-level evaluation (`evaluation/research/passage_eval.py`).** 14 IBM questions with gold documents × EN/DE
(28 queries), 28 atomic answer facts, 44 gold passages. Each fact's supporting passages were identified by an
author-written pattern whose matches over all 354 passages were reviewed by hand (e.g. the 2015 Blopress dose is
excluded for "current antihypertensive"). Gold file kept private. Retrieval uses the production term extraction
with one search step:

| Mode | fact recall@6 | fact recall@10 | passage recall@10 | MRR | nDCG@10 | median / max |
|---|---|---|---|---|---|---|
| lexical | 0.089 | 0.089 | 0.086 | 0.126 | 0.081 | 4 ms / 15 ms |
| dense | 0.488 | 0.571 | 0.429 | 0.430 | 0.381 | 231 ms / 451 ms |
| hybrid, equal RRF | 0.518 | 0.601 | 0.445 | 0.489 | 0.399 | 254 ms / 493 ms |
| hybrid, tuned | 0.476 | 0.512 | 0.423 | 0.517 | 0.411 | 265 ms / 429 ms |
| hybrid + reranker | 0.565 | 0.631 | 0.475 | 0.553 | 0.455 | 6.98 s / 11.9 s |

End to end (`run_task`, heuristic planner, structured retrieval + passage search + verification), share of answer
facts whose supporting text is cited by a claim: lexical 0.964 (supported claims 0.964), auto/dense 0.964 (0.964);
median 0.47 s vs 0.79 s, max 0.93 s vs 1.25 s. The single miss is 1.3-de (EF 60%).

Interpretation: the 98% document-level hit rate in §2 is **not** retrieval accuracy for answers: at passage level dense
finds a supporting passage for 57% of facts in the top 10. End-to-end completeness is high mainly because structured
facts (medications, observations, diagnoses) answer most of these questions, and the lexicon was tuned on them.
At passage level the differences between dense and the hybrid variants are small and inconsistent across metrics
(equal RRF wins fact recall, tuned wins MRR/nDCG, the opposite of the document-level ranking); only the reranker is
consistently better, at ~7 s per search step on CPU. 28 queries over one patient: no significance claims.
