# Scientific implementation report (hackathon submission)

Synthetic-data research prototype. Nothing below is a clinical validation. "Executed" means the model or algorithm
actually ran on the private IBM synthetic patient in this repository. "Evaluated" means it was scored against
labels we wrote ourselves. **No paper has been reproduced**: each method was run as published, without retraining,
and scored on our data. Details and every number: `docs/research/EXPERIMENTS.md` and `IMPLEMENTATION_MATRIX.md`.

## System (seven layers, one Docker Compose deployment)

| Layer | What runs in the demo |
|---|---|
| 1 Ingestion | Source mapping with offsets and SHA-256 checksums; medSpaCy sectionizer with German rules |
| 2 Extraction | German rules plus ConText/NegEx; optional GERNERMED++ (separate environment) and grounded Groq LLM extraction (LLM facts always need review) |
| 3 Storage | PostgreSQL 16 + pgvector, Alembic migrations 0001–0003, patient isolation, as-of-date queries |
| 4 Planning | Groq `openai/gpt-oss-120b` planner, capped at 8 s with no retries; rule-based fallback, reported in every response |
| 5 Retrieval | Structured facts first, then passage search. `auto` = BGE-M3 dense via the `models` service; keyword fallback is reported. Also `lexical`, `hybrid` (weighted RRF), `hybrid_rerank` |
| 6 Verification | Strict citation integrity (document version, patient, passage, offsets, quote, checksum); value/negation support checks; conflict detection; VeriFact-style claim verification (`POST /api/verify`) |
| 7 Presentation | FastAPI with a stable OpenAPI contract (`docs/openapi.json`, TS types) and a React UI where citations open the original German passage |

## Status classes

- **Implemented and executed in the main demo flow (`POST /api/tasks`, `POST /api/v1/clinical-tasks`):** Layer 1
  source mapping + medSpaCy sectionizer, Layer 2 German rules + ConText, Layer 3 PostgreSQL/pgvector, Layer 4 rule
  planner (validated require-term and ATC filters), Layer 5 structured-first retrieval with BGE-M3 dense passage
  search, Layer 6 strict citation integrity + deterministic value/negation support + conflict detection, Layer 7
  Lovable frontend on the live API (`/api/v1`, repo jromero158486/screenshot-match).
- **Optional integrations (implemented and executed, opt-in, not in the main flow):** VeriFact-style claim
  verification with multilingual NLI ("Verify clinical statement" → `POST /api/v1/verify-statement`, never run
  automatically); Groq LLM planner (`PLANNER=llm`; in the demo it dropped the rule planner's safety filters, so
  dense search returned unrelated passages for undocumented items); Groq judge (`judge=groq`); `hybrid` and
  `hybrid_rerank` retrieval modes; Groq grounded extraction at ingest (`--llm`); GERNERMED++ (VM only).
- **Deferred research features (not implemented):** temporal knowledge graph, FHIR R4/ELGA export, constrained
  ReAct-style agent, SNOMED CT linking, restricted-access benchmarks.

## Methods actually executed

| Method (paper) | Licence | Status | Key result on our data |
|---|---|---|---|
| medSpaCy sectionizer + ConText (Eyre 2021; Harkema 2009) | MIT | executed (VM + Docker) | 51/51 headings; German ConText kept as the default (handles "St.p.", "V.a.") |
| GERNERMED++ (Frei 2023) | no licence file | executed on the VM only (spaCy 3.2 conflict) | agrees on 21/21 drugs; adds no correct new medication; finds 7/20 dosing schedules |
| Grounded LLM extraction | Groq API | executed | 40–45 extra facts with exact source quotes, all marked "needs review"; extraction scores unchanged |
| BioC (Comeau 2013) | MIT | executed | facts exported with offsets into the original text |
| BGE-M3 dense/sparse/multi-vector (Chen 2024) | MIT | executed, **default in Docker** | document-level Recall@10 0.98 vs keyword 0.28; passage-level fact recall@10 0.57 vs 0.09 |
| bge-reranker-v2-m3 | Apache-2.0 | executed, opt-in | best passage-level mode (fact recall@10 0.63, MRR 0.55), but ~6–7 s per search step on CPU |
| Reciprocal Rank Fusion (Cormack 2009) | — | executed; weights tuned on separate validation queries | equal-weight fusion hurt (validation MRR 0.53 vs dense 0.87), so it is not the default |
| pgvector | PostgreSQL licence | executed | 354 passages indexed; the existing volume was migrated |
| VeriFact (Chung 2025) — adaptation | MIT | executed, `POST /api/verify` | held-out claims: false-support rate 0.20 → **0.00** with NLI; contradiction recall 0.00 → 0.55 (NLI) / 0.82 (Groq judge) |
| mDeBERTa-v3 multilingual NLI | MIT | executed (VM + Docker `models` service) | judge in VeriFact-style verification, ~0.6 s per claim |

Not executed or blocked: SNOMED CT (licence), CARDIO:DE, ArchEHR-QA, MedAlign and VeriFact-BHC data (restricted
access), FHIR export, temporal knowledge graph and the ReAct-style agent (deferred until after the demo).

## Benchmarks (one synthetic patient, 8 documents)

**IBM benchmark (15 questions) plus 10 tasks we wrote ourselves.** Rule-based planner: 57/61 key terms found; exact
expected values in supported claims 27/28 (IBM) and 23/23 (own tasks); every citation valid. These checks are
automatic text matching, not clinical judgement, and the vocabulary was tuned on the same questions.

**Retrieval, passage level** (28 EN/DE queries, 28 atomic answer facts, 44 hand-reviewed gold passages):

| Mode | fact recall@10 | MRR | nDCG@10 | median latency |
|---|---|---|---|---|
| lexical | 0.09 | 0.13 | 0.08 | 4 ms |
| BGE-M3 dense (default) | 0.57 | 0.43 | 0.38 | 0.23 s |
| hybrid + reranker | 0.63 | 0.55 | 0.46 | 7.0 s |

End to end (structured facts + passages): 96% of answer facts are cited by a claim, with either retrieval mode.

**Claim verification, held-out set** (34 German/English claims about the synthetic patient):

| Configuration | accuracy | false-support rate | contradiction recall |
|---|---|---|---|
| deterministic checks only | 0.50 | 0.20 | 0.00 |
| deterministic + NLI (default) | 0.68 | 0.00 | 0.55 |
| deterministic + Groq judge | 0.77 | 0.00 | 0.82 |

**Deployed latency** (Docker, warmed, CPU only, unseen DE/EN tasks through the frontend proxy): 0.6–3.2 s per task.
Citations matched their source document 100% of the time, the 8 known source conflicts are reported, and missing
information is listed separately (e.g. "Smoking status: not documented").

## Limitations

- One synthetic patient. All labels (passage gold, claims) were written by the authors, with no clinician review and
  no significance testing.
- "supported" means the claim is entailed by cited record text and has no value/date/negation mismatch. It is
  **not** clinical verification (`clinically_verified` is always false).
- Value parsing is literal: ranges such as "47 - 100 (67)/min" and blood-pressure ratios can make a correct claim
  go to review.
- Groq latency and rate limits vary. The planner falls back to the rule-based planner after 8 s, and the response
  says so.
- The reranker is too slow for interactive CPU use. GERNERMED++ is not in Docker.
- No authentication: demo-only, ports bound to loopback (`docs/SECURITY_AND_AUTH.md`).
